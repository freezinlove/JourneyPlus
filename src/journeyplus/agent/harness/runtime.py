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
                         item.result_max_bytes,item.operation_result_max_bytes,item.result_budget_field)
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
            await self._calls(run_id, owner, context, budget, state['pending_calls'], messages)
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
            projected = await blocking_call(project, messages, definitions, capabilities, note=note, focus=workspace_state.get('focus'),
                                reserved_output=budget.limits(capabilities)['max_output'])
            estimator=getattr(self.ports.model,'estimate_input',None)
            projected_tokens = estimator(projected,definitions) if estimator else estimate([m.model_dump(mode='json') for m in projected]) + estimate([{'name':d.name,'description':d.description,'parameters':d.input_schema} for d in definitions])
            final_estimator=getattr(self.ports.model,'estimate_final_input',None)
            # The next final request also carries this model response and its
            # observations. Reserving only the pre-call history can strand a
            # large tool result without enough input budget to explain it.
            growth_bytes=6000+3*budget.limits(capabilities)['max_output']
            future=projected+[ModelMessage(role='system',content=[Part(type='text',text='x'*growth_bytes)])]
            final_tokens=final_estimator(future,definitions) if final_estimator else projected_tokens+estimate('x'*growth_bytes)
            if not budget.finalizing and (budget.input_tokens + projected_tokens + final_tokens >= budget.hard['input_tokens']
                    or budget.requests+2>budget.hard['requests'] or budget.tools>=budget.hard['tools']
                    or budget.output_tokens+1024>=budget.hard['output_tokens']):
                budget.finalizing = True
                notice = 'Resource reserve: provide a final response from available evidence; no more tool calls.'
                projected.append(ModelMessage(role='system',content=[Part(type='text',text=notice)]))
                await self._publish(run_id, owner,'resource.notice',{'message':'正在根据已取得的资料整理回答。'})
            if budget.finalizing and final_estimator:
                projected_tokens=final_estimator(projected,definitions)
            if budget.input_tokens + projected_tokens > budget.hard['input_tokens']:
                return 'PARTIAL'
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
                if repeated['count'] >= 3:
                    call['runtime_error'] = 'REPEATED_CALL'
                    call['prior_result_refs'] = list(repeated.get('result_refs', []))
                if repeated['count'] > 3:
                    repeated['stop'] = True
            await self._calls(run_id, owner, context, budget, calls, messages)
            if repeated.get('stop'):
                return 'PARTIAL'
        return 'CANCELED' if context.cancel_token.is_set() else 'PARTIAL'

    async def _calls(self, run_id, owner, context, budget, calls, messages):
        (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, phase='TOOLS_PENDING', pending_calls=calls, remaining_budget=budget.snapshot()))
        semaphore = asyncio.Semaphore(3)
        results = [None]*len(calls)
        reads = []
        # Once calls are known, admit their declared maximum observations before
        # executing effects. Reserve an error response instead of silently losing
        # an executed result when a large batch cannot fit the final request.
        capacities=[]
        for call in calls:
            validated,_=self.ports.registry.validate(call['name'],call['arguments'])
            if validated:
                definition,arguments,_=validated
                capacity=definition.operation_result_max_bytes.get(getattr(arguments,definition.result_budget_field,None),definition.result_max_bytes)
            else:capacity=2000
            capacities.append(min(capacity,32000//max(1,len(calls))))
        if not budget.finalizing:
            definitions=self.ports.registry.definitions()
            workspace_state=(await blocking_call(self.ports.sessions.load_context_index,context.workspace_id)).get('state',{})
            note=(await blocking_call(self.ports.artifacts.read,context.workspace_id,workspace_state['note_ref']))['payload'] if workspace_state.get('note_ref') else None
            projected=await blocking_call(project,messages,definitions,self.ports.model.capabilities(),note=note,focus=workspace_state.get('focus'),
                              reserved_output=budget.limits(self.ports.model.capabilities())['max_output'])
            future=projected+[ModelMessage(role='system',content=[Part(type='text',text='x'*sum(capacities))])]
            estimator=getattr(self.ports.model,'estimate_final_input',None)
            final_size=estimator(future,definitions) if estimator else estimate([m.model_dump(mode='json') for m in future])
            if budget.input_tokens+final_size>budget.hard['input_tokens']:
                budget.finalizing=True
                await self._publish(run_id,owner,'resource.notice',{'code':'OBSERVATION_RESERVE',
                    'message':'剩余预算不足以容纳本批工具结果及收尾，已保留完成的操作，本批新动作未执行。'})

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
                elif len(calls) > 8:
                    result = ToolResult.failure('INVALID_ARGUMENT', 'At most eight calls per batch')
                elif call.get('runtime_error'):
                    result = ToolResult.failure(call['runtime_error'], 'Repeated call without progress; use prior results or change approach')
                    result.data['prior_result_refs'] = call.get('prior_result_refs', [])
                    result.artifact_refs = call.get('prior_result_refs', [])
                elif validated is None:
                    _, result = self.ports.registry.validate(call['name'], call['arguments'])
                else:
                    budget.tools += 1
                    await self._publish(run_id, owner, 'tool.started', {'call_id': call['call_id'], 'label': validated[0].progress_label})
                    async with semaphore:
                        result = await self.ports.registry.execute(validated, local)
                result.call_id = call['call_id']
                full_ref = (await blocking_call(self.ports.sessions.tool_result, run_id, owner, call, result))
            fingerprint = call.get('progress_fingerprint')
            if not call.get('runtime_error') and budget.repeat_state.get('fingerprint') == fingerprint:
                budget.repeat_state['result_refs'] = [*budget.repeat_state.get('result_refs', []),full_ref][-2:]
            from .context import bounded_result
            capacity=12000
            if validated:
                definition,arguments,_=validated
                capacity=definition.operation_result_max_bytes.get(getattr(arguments,definition.result_budget_field,None),definition.result_max_bytes)
            result = bounded_result(result, full_ref, max_bytes=min(capacity, 32000//max(1,len(calls))),
                                    trim=validated[0].trim_projection if validated else None)
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
        paired = {p.call_id for m in messages if m.metadata.get('turn_id')==context.turn_id for p in m.content if p.type == 'tool_result'}
        for call, result in zip(calls, results):
            if call['call_id'] in paired:
                continue
            message = ModelMessage(role='tool', content=[Part(type='tool_result', call_id=call['call_id'], result=result.model_dump(mode='json'))])
            (await blocking_call(self.ports.sessions.append_message, run_id, owner, message))
            messages.append(message)
        (await blocking_call(self.ports.sessions.save_checkpoint, run_id, owner, phase='READY_MODEL', pending_calls=[], remaining_budget=budget.snapshot()))
