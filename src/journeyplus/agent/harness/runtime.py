"""Single model/tool loop. Lifecycle policy never branches on business meaning."""
import asyncio
from dataclasses import replace
import json
import hashlib
from uuid import uuid4

from .budget import Budget, estimate
from .execution import blocking_call
from .context import project, ContextCapacityError, CONTEXT_POLICY_VERSION
from .contracts import ExecutionContext, ModelMessage, Part, ToolResult, ModelUnavailable


class Runtime:
    def __init__(self, ports, instructions, services=None, budget_limits=None):
        self.ports = ports
        self.instructions = instructions
        self.services = services or {}
        self.budget_limits=budget_limits or {}
        self.cancellations = {}
        self.running_tasks = {}
        self.tool_tasks = {}

    async def _publish(self, run_id, owner, kind, payload):
        (await blocking_call(self.ports.events.append_and_publish, run_id, kind, payload, owner=owner))

    async def cancel(self, run_id):
        token = self.cancellations.get(run_id)
        if token:
            token.set()
        task = self.running_tasks.get(run_id)
        if task:
            task.cancel()
        await blocking_call(self.ports.sessions.request_cancel, run_id)

    async def run(self, run_id):
        owner = str(uuid4())
        token = self.cancellations.setdefault(run_id, asyncio.Event())
        self.running_tasks[run_id] = asyncio.current_task()
        try:
            state = await blocking_call(self.ports.sessions.claim_run, run_id, owner)
        except asyncio.CancelledError:
            token.set()
            await blocking_call(self.ports.sessions.request_cancel,run_id)
            await blocking_call(self.ports.sessions.finish_run,run_id,owner,'CANCELED')
            self.cancellations.pop(run_id,None)
            self.running_tasks.pop(run_id,None)
            return
        except Exception:
            self.cancellations.pop(run_id,None)
            self.running_tasks.pop(run_id,None)
            raise
        if not state:
            self.cancellations.pop(run_id,None)
            self.running_tasks.pop(run_id,None)
            return
        if state.get('cancel_requested'):
            token.set()
        budget = Budget()
        budget.soft.update(self.budget_limits.get('soft',{}))
        budget.hard.update(self.budget_limits.get('hard',{}))
        saved = state.get('budget') or {}
        for key in ('requests', 'tools', 'input_tokens', 'output_tokens', 'estimated', 'notified', 'finalizing', 'repeat_state'):
            if key in saved:
                setattr(budget, key, saved[key])
        budget.started -= saved.get('seconds', 0)
        configuration=[getattr(self.ports.model,'configuration_id',None),self.instructions,self.budget_limits,CONTEXT_POLICY_VERSION,
                       [(item.name,item.version,item.description,item.input_schema,item.output_schema,item.effect,item.operation_effects,
                         item.result_max_bytes,item.operation_result_max_bytes,item.result_budget_field,item.complete_result_operations)
                        for item in self.ports.registry.definitions()]]
        budget.model_configuration_id=hashlib.sha256(json.dumps(configuration,sort_keys=True).encode()).hexdigest()
        workspace_id = state['workspace_id']
        context = ExecutionContext(workspace_id, state['turn_id'], '', 'local-user',
            budget.started+budget.hard['seconds'], token, self.ports.artifacts, self.ports.workspace, self.services, run_id, owner)
        heartbeat = asyncio.create_task(self._heartbeat(run_id, owner, token))
        status = 'FAILED'
        try:
            status = await self._loop(run_id, owner, context, budget, state)
        except asyncio.CancelledError:
            status = 'CANCELED'
        except ContextCapacityError:
            status = 'PARTIAL'
            await self._publish(run_id, owner, 'resource.notice', {'code':'CONTEXT_CAPACITY',
                'message':'本轮证据已达到上下文容量，完整记录和已完成操作已保留；可在新一轮继续读取。'})
        except Exception:
            try:await self._publish(run_id, owner, 'resource.notice', {'code': 'RUNTIME_FAILURE', 'message': '运行中断，已完成操作保留。'})
            except Exception:pass  # A displaced worker must not publish over the new lease.
        finally:
            pending = self.tool_tasks.pop(run_id, set())
            for task in pending:task.cancel()
            if pending:await asyncio.gather(*pending, return_exceptions=True)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            (await blocking_call(self.ports.sessions.finish_run, run_id, owner, status))
            self.cancellations.pop(run_id, None)
            self.running_tasks.pop(run_id, None)

    async def _heartbeat(self, run_id, owner, token):
        while True:
            await asyncio.sleep(10)
            try:
                alive = (await blocking_call(self.ports.sessions.heartbeat, run_id, owner))
            except Exception:
                alive = False
            if not alive:
                token.set()
                task = self.running_tasks.get(run_id)
                if task:task.cancel()
                return

    async def _loop(self, run_id, owner, context, budget, state):
        if (state.get('budget') or {}).get('delivery_complete'):
            return 'CANCELED' if context.cancel_token.is_set() else 'COMPLETED'
        previous_configuration=(state.get('budget') or {}).get('model_configuration_id')
        if previous_configuration and previous_configuration!=budget.model_configuration_id:
            await self._publish(run_id,owner,'resource.notice',{'code':'MODEL_CONFIGURATION_CHANGED','message':'模型、指令或工具配置已改变，保留上次结果，请发起新一轮。'})
            return 'PARTIAL'
        messages = (await blocking_call(self.ports.sessions.load_context_index, context.workspace_id))['messages']
        messages = [m for m in messages if m.metadata.get('turn_id') == context.turn_id
                    or not (m.metadata.get('completion_rejected') or m.metadata.get('completion_feedback'))]
        messages = [ModelMessage(role='system', content=[Part(type='text', text=self.instructions)])] + messages
        if state.get('interrupted'):
            notice = ModelMessage(role='system', content=[Part(type='text', text='runtime_interruption: Previous execution was interrupted. Reuse completed receipts. Incomplete text is marked interrupted.')])
            messages.append(notice)
        if state.get('pending_calls'):
            if await self._calls(run_id, owner, context, budget, state['pending_calls'], messages):
                return 'CANCELED' if context.cancel_token.is_set() else 'COMPLETED'
        repeated = budget.repeat_state
        format_failures = empty = 0
        while not context.cancel_token.is_set() and not budget.reached('hard'):
            if budget.reached('soft') and not budget.notified:
                budget.notified = True
                notice = {'remaining': {k: v-budget.values()[k] for k, v in budget.hard.items()}, 'message': 'Soft resource warning. Tools remain available while final-response reserve fits. Prioritize missing deliverables, avoid redundant reads, and report any unfinished work.'}
                await self._publish(run_id, owner, 'resource.notice', notice)
                messages.append(ModelMessage(role='system', content=[Part(type='text', text=json.dumps(notice))]))
            (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, phase='MODEL_RUNNING', remaining_budget=budget.snapshot()))
            definitions = self.ports.registry.definitions()
            capabilities = self.ports.model.capabilities()
            workspace_state = (await blocking_call(self.ports.sessions.load_context_index, context.workspace_id)).get('state', {})
            note = None
            if workspace_state.get('note_ref'):
                note = (await blocking_call(self.ports.artifacts.read, context.workspace_id, workspace_state['note_ref']))['payload']
            visible, focus = messages, workspace_state.get('focus')
            if self.ports.views:
                visible, note, focus = await blocking_call(self.ports.views.context, context.workspace_id, messages, note, focus)
            projected = await blocking_call(project, visible, definitions, capabilities, note=note, focus=focus,
                                reserved_output=budget.limits(capabilities)['max_output'],
                                context_token_budget=self.budget_limits.get('context_tokens',500000),
                                input_estimator=getattr(self.ports.model,'estimate_input',None))
            estimator=getattr(self.ports.model,'estimate_input',None)
            projected_tokens = estimator(projected,definitions) if estimator else estimate([m.model_dump(mode='json') for m in projected]) + estimate([{'name':d.name,'description':d.description,'parameters':d.input_schema} for d in definitions])
            # Reserve time to answer; token usage and call counts are telemetry only.
            if not budget.finalizing and budget.values()['seconds'] >= budget.hard['seconds'] - 45:
                budget.finalizing = True
                projected.append(ModelMessage(role='system',content=[Part(type='text',text=
                    'Time reserve: finish your answer using available results; no more tool calls.')]))
                await self._publish(run_id,owner,'resource.notice',{'message':'接近耗时上限，正在整理已有结果。'})
            budget.requests += 1
            reserved = budget.snapshot()
            reserved['input_tokens'] += projected_tokens
            reserved['output_tokens'] += budget.limits(capabilities)['max_output']
            reserved['estimated'] = True
            (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, phase='MODEL_RUNNING', model_attempt=budget.requests, remaining_budget=reserved))
            parts, calls, text, usage, finish = [], [], '', None, None
            protocol_feedback = ''
            model_failure = None
            message_id = str(uuid4())
            await self._publish(run_id, owner, 'assistant.started', {'message_id': message_id})
            try:
                async with asyncio.timeout(budget.limits(capabilities)['timeout']):
                    limits = budget.limits(capabilities)
                    async for event in self.ports.model.stream(projected, definitions, limits, context.cancel_token):
                        if context.cancel_token.is_set():
                            break
                        if event.type == 'text_delta':
                            text += event.text or ''
                            await self._publish(run_id, owner, 'text_delta', {'message_id': message_id, 'text': event.text})
                        elif event.type == 'tool_call_ready':
                            calls.append({'call_id': event.call_id, 'name': event.name, 'arguments': event.arguments})
                        elif event.type == 'usage':
                            usage = event.usage
                        elif event.type == 'turn_end':
                            finish = event.finish_reason
            except asyncio.CancelledError:
                context.cancel_token.set()
                finish = 'error'
            except ModelUnavailable as exc:
                finish='error'
                model_failure=exc
            except (ValueError, TimeoutError) as exc:
                finish = 'error'
                if hasattr(exc,'errors'):
                    protocol_feedback = json.dumps([{'field':'.'.join(map(str,e['loc'])),'error':e['type']} for e in exc.errors(include_input=False)],ensure_ascii=False)
                elif isinstance(exc,ValueError):protocol_feedback = str(exc)[:500]
            budget.usage(usage, projected_tokens, estimate({'text':text,'calls':calls}))
            (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, remaining_budget=budget.snapshot()))
            if text:
                parts.append(Part(type='text', text=text))
            if finish not in {'stop', 'tool_calls'} or context.cancel_token.is_set():
                if parts:
                    interrupted = ModelMessage(id=message_id, role='assistant', content=parts,
                        metadata={'interrupted': True})
                    (await blocking_call(self.ports.sessions.append_message, run_id, owner, interrupted))
                    messages.append(interrupted)
                    await self._publish(run_id, owner, 'assistant.interrupted', {'message_id': message_id})
                if context.cancel_token.is_set():
                    return 'CANCELED'
                if model_failure:
                    await self._publish(run_id,owner,'resource.notice',{'code':'MODEL_UNAVAILABLE','http_status':model_failure.status,
                        'provider_code':model_failure.code,'message':'模型服务暂不可用，已保留本轮取得的结果。'})
                    return 'PARTIAL'
                format_failures += 1
                if format_failures > 1:
                    return 'PARTIAL'
                messages.append(ModelMessage(role='system', content=[Part(type='text', text='INVALID_MODEL_OUTPUT: Complete valid tool parameters or provide an answer. No incomplete calls were executed. '+protocol_feedback)]))
                continue
            format_failures = 0
            if calls:
                parts.extend(Part(type='tool_call', **{key:call[key] for key in ('call_id','name','arguments')}) for call in calls)
            message = ModelMessage(id=message_id, role='assistant', content=parts)
            (await blocking_call(self.ports.sessions.append_message, run_id, owner, message))
            messages.append(message)
            if not calls:
                if text:
                    return 'COMPLETED'
                empty += 1
                if empty > 1:
                    return 'PARTIAL'
                messages.append(ModelMessage(role='system', content=[Part(type='text', text='EMPTY_RESPONSE: Provide a final response using available results.')]))
                continue
            for call in calls:
                validated,_=self.ports.registry.validate(call['name'],call['arguments'])
                snapshot=await blocking_call(validated[0].snapshot,validated[1],context) if validated and validated[0].snapshot else None
                arguments=validated[1].model_dump(mode='json') if validated else call['arguments']
                fingerprint = json.dumps([call['name'], arguments, snapshot], sort_keys=True, ensure_ascii=False)
                call['progress_fingerprint']=fingerprint
                previous = repeated.get('fingerprint')
                repeated['count'] = repeated.get('count', 0)+1 if previous == fingerprint else 1
                if previous != fingerprint:
                    repeated['result_refs'] = []
                repeated['fingerprint'] = fingerprint
                if (repeated['count'] >= 2 and validated and validated[2]=='READ' and snapshot is not None
                        and not arguments.get('refresh') and repeated.get('result_refs')):
                    call['reuse_result_ref'] = repeated['result_refs'][-1]
            if await self._calls(run_id, owner, context, budget, calls, messages):
                return 'CANCELED' if context.cancel_token.is_set() else 'COMPLETED'
        return 'CANCELED' if context.cancel_token.is_set() else 'PARTIAL'

    async def _calls(self, run_id, owner, context, budget, calls, messages):
        (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, phase='TOOLS_PENDING', pending_calls=calls, remaining_budget=budget.snapshot()))
        semaphore = asyncio.Semaphore(3)
        results = [None]*len(calls)
        reads = []
        async def execute(index, call, validated):
            effect = validated[2] if validated else 'READ'
            if validated:call['tool_version']=validated[0].version
            local = replace(context, call_id=call['call_id'])
            cached = (await blocking_call(self.ports.sessions.tool_intent, run_id, owner, call, effect))
            if cached is not None:
                result = ToolResult.model_validate(cached['result'])
                full_ref = cached['full_ref']
            else:
                if context.cancel_token.is_set() or budget.reached('hard') or budget.finalizing:
                    result = ToolResult.failure('BUDGET_LIMIT', 'No new calls may start after cancellation or budget exhaustion')
                elif call.get('reuse_result_ref'):
                    stored = await blocking_call(self.ports.artifacts.read, context.workspace_id, call['reuse_result_ref'])
                    result = ToolResult.model_validate(stored['payload']).model_copy(deep=True)
                    result.cache = {**result.cache, 'reused': True}
                elif validated is None:
                    _, result = self.ports.registry.validate(call['name'], call['arguments'])
                else:
                    budget.tools += 1
                    await self._publish(run_id, owner, 'tool.started', {'call_id': call['call_id'], 'label': validated[0].progress_label})
                    async with semaphore:
                        result = await self.ports.registry.execute(validated, local)
                result.call_id = call['call_id']
                full_ref = (await blocking_call(self.ports.sessions.tool_result, run_id, owner, call, result))
            if self.ports.views:
                result = await blocking_call(self.ports.views.result, context.workspace_id, result)
            fingerprint = call.get('progress_fingerprint')
            if not result.error and result.status=='OK' and budget.repeat_state.get('fingerprint') == fingerprint:
                budget.repeat_state['result_refs'] = [*budget.repeat_state.get('result_refs', []),full_ref][-2:]
            if validated and validated[0].model_projection:
                result=validated[0].model_projection(result)
            result.coverage['full_result_ref']=full_ref
            result.artifact_refs=list(dict.fromkeys([*result.artifact_refs,full_ref]))
            await self._publish(run_id, owner, 'tool.completed', {'call_id': call['call_id'], 'status': result.status,
                'summary': result.error.message if result.error else result.data.get('summary', ''), 'artifact_refs': result.artifact_refs})
            return result

        for index, call in enumerate(calls):
            validated, _ = self.ports.registry.validate(call['name'], call['arguments'])
            if validated is not None and validated[2] == 'READ':
                task = asyncio.create_task(execute(index, call, validated))
                self.tool_tasks.setdefault(run_id, set()).add(task)
                reads.append((index, task))
            else:
                # Flush preceding reads before a write to preserve selected effect order.
                for i, task in reads:
                    results[i] = await task
                reads = []
                results[index] = await execute(index, call, validated)
        for index, task in reads:
            results[index] = await task
        complete_indices=[index for index,result in enumerate(results) if not result.error]
        if complete_indices:
            from .context import ContextCapacityError
            # Check the whole batch together, including paired call/result
            # overhead and any remaining history. Never silently send an excerpt.
            while True:
                additions=[ModelMessage(role='tool',content=[Part(type='tool_result',call_id=c['call_id'],result=r.model_dump(mode='json'))])
                           for c,r in zip(calls,results)]
                try:
                    definitions=self.ports.registry.definitions()
                    workspace_state=(await blocking_call(self.ports.sessions.load_context_index,context.workspace_id)).get('state',{})
                    note=(await blocking_call(self.ports.artifacts.read,context.workspace_id,workspace_state['note_ref']))['payload'] if workspace_state.get('note_ref') else None
                    visible,focus=messages+additions,workspace_state.get('focus')
                    if self.ports.views:
                        visible,note,focus=await blocking_call(self.ports.views.context,context.workspace_id,visible,note,focus)
                    projected=await blocking_call(project,visible,definitions,self.ports.model.capabilities(),note=note,focus=focus,
                        reserved_output=budget.limits(self.ports.model.capabilities())['max_output'],
                        context_token_budget=self.budget_limits.get('context_tokens',500000),
                        input_estimator=getattr(self.ports.model,'estimate_input',None))
                    estimator=getattr(self.ports.model,'estimate_input',None)
                    tokens=estimator(projected,definitions) if estimator else estimate([m.model_dump(mode='json') for m in projected])+estimate([{'name':d.name,'description':d.description,'parameters':d.input_schema} for d in definitions])
                    fits=tokens<=self.budget_limits.get('context_tokens',500000)
                except ContextCapacityError:
                    fits=False
                if fits:
                    break
                changed=False
                for index in sorted(complete_indices,key=lambda i:len(results[i].model_dump_json()),reverse=True):
                    validated,_=self.ports.registry.validate(calls[index]['name'],calls[index]['arguments'])
                    paginator=validated[0].capacity_page if validated else None
                    smaller=paginator(results[index]) if paginator else None
                    if smaller is not None:
                        results[index]=smaller
                        changed=True
                        break
                if not changed:
                    break
            if not fits:
                for index in complete_indices:
                    original=results[index]
                    results[index]=ToolResult.failure('CONTEXT_CAPACITY',
                        '本批资料超出可用上下文，完整结果已保存。请使用 full_result_ref 选择相关业务章节或较小分页；本批内容尚未完整读取。')
                    results[index].call_id=calls[index]['call_id']
                    results[index].artifact_refs=original.artifact_refs
                    results[index].coverage={'complete':False,'omissions':['complete_body_not_delivered'],
                        'full_result_ref':original.coverage['full_result_ref']}
                    await self._publish(run_id,owner,'resource.notice',{'code':'CONTEXT_CAPACITY',
                        'call_id':calls[index]['call_id'],'message':results[index].error.message})
        paired = {p.call_id for m in messages if m.metadata.get('turn_id')==context.turn_id for p in m.content if p.type == 'tool_result'}
        for call, result in zip(calls, results):
            if call['call_id'] in paired:
                continue
            message = ModelMessage(role='tool', content=[Part(type='tool_result', call_id=call['call_id'], result=result.model_dump(mode='json'))])
            (await blocking_call(self.ports.sessions.append_message, run_id, owner, message))
            messages.append(message)
        # Only an explicitly final, wholly successful delivery batch may end a
        # turn. Mixed reads/writes and failures must return observations to the
        # model. Keep this generic: the registry owns each capability's policy.
        terminal = bool(calls)
        for call, result in zip(calls, results):
            validated, _ = self.ports.registry.validate(call['name'], call['arguments'])
            terminal = terminal and bool(validated and not result.error and result.status == 'OK'
                and validated[0].completes_turn
                and validated[0].completes_turn(validated[1], result))
        (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, phase='READY_MODEL', pending_calls=[],
            remaining_budget={**budget.snapshot(), 'delivery_complete': terminal}))
        return terminal
