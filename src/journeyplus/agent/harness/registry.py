"""Schema validation and effect dispatch, independent of tool semantics."""
import asyncio
from dataclasses import replace
import json
from time import monotonic
from pydantic import ValidationError
from .contracts import ToolDefinition, ToolResult
from .execution import active_call, blocking_call


class Registry:
    def __init__(self):
        self._definitions = {}

    def register(self, definition: ToolDefinition):
        if definition.name in self._definitions:
            raise ValueError('Duplicate tool name')
        if definition.complete_result_operations and (definition.effect!='READ' or definition.operation_effects):
            raise ValueError('Complete observations are only supported for read-only tools')
        self._definitions[definition.name] = definition

    def definitions(self):
        return list(self._definitions.values())

    def validate(self, name, arguments):
        definition = self._definitions.get(name)
        if definition is None:
            return None, ToolResult.failure('UNKNOWN_TOOL', 'Available tools: ' + ', '.join(self._definitions))
        try:
            parsed = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            errors = exc.errors()
            missing = ['.'.join(map(str, e['loc'])) for e in errors if e['type'] == 'missing']
            message = '工具参数未通过校验，本次工具没有执行；这不是业务查询无结果。'
            if missing:
                message += ' 缺少必需参数：' + '、'.join(missing) + '。'
            else:
                message += ' 具体字段问题见 fields。'
            return None, ToolResult.failure('INVALID_ARGUMENT', message,
                fields=[{'path': list(e['loc']), 'message': e['msg']} for e in errors])
        if definition.operation_effects:
            effect = definition.operation_effects.get(getattr(parsed, 'operation', None))
            if effect is None:
                return None, ToolResult.failure('INVALID_ARGUMENT', 'Unregistered operation')
        else:
            effect = definition.effect
        return (definition, parsed, effect), None

    async def execute(self, validated, context):
        definition, arguments, _ = validated
        started = monotonic()
        if context.cancel_token.is_set():
            return ToolResult.failure('CANCELED', 'Call canceled before execution')
        try:
            timeout = min(definition.timeout_seconds, context.deadline - monotonic())
            if timeout <= 0:
                return ToolResult.failure('BUDGET_LIMIT', 'Call deadline exhausted')
            local=replace(context,deadline=monotonic()+timeout)
            token=active_call.set(local)
            try:
                async with asyncio.timeout(timeout):
                    result = await definition.handler(arguments, local)
            finally:active_call.reset(token)
            validated_result = definition.output_model.model_validate(result.model_dump(mode='json') if isinstance(result,ToolResult) else result)
            result = ToolResult.model_validate(validated_result.model_dump(mode='json',exclude_unset=True))
        except TimeoutError:
            result = ToolResult.failure('SOURCE_UNAVAILABLE', 'Tool timed out', retryable=True)
        except ValidationError:
            result = ToolResult.failure('INVALID_TOOL_RESULT', 'Tool returned data outside its declared output contract')
        except LookupError as exc:
            result = ToolResult.failure('NOT_FOUND', str(exc)[:500], status='NOT_FOUND')
        except ValueError as exc:
            code = 'STALE_REFERENCE' if str(exc).startswith('STALE_REFERENCE:') else 'INVALID_ARGUMENT'
            result = ToolResult.failure(code, str(exc)[:500])
        except asyncio.CancelledError:
            raise
        except Exception:
            result = ToolResult.failure('TOOL_ERROR', 'Tool execution failed', retryable=True)
        if result.error and result.error.code in {'SOURCE_UNAVAILABLE','TOOL_ERROR','INVALID_TOOL_RESULT'} and validated[2]=='USER_WRITE' and context.authorization_port:
            committed=await blocking_call(context.authorization_port.committed_call_result,
                context.workspace_id,context.turn_id,context.call_id)
            if committed is not None:
                committed.metrics['post_commit_error_code']=result.error.code
                result=committed
        result.call_id = context.call_id
        result.effective_input = result.effective_input or arguments.model_dump(mode='json', exclude_unset=True)
        result.metrics['elapsed_ms'] = round((monotonic() - started) * 1000)
        return result
