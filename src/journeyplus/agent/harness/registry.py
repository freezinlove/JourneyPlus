"""Schema validation and effect dispatch, independent of tool semantics."""
import asyncio
import json
from time import monotonic
from pydantic import ValidationError
from .contracts import ToolDefinition, ToolResult


class Registry:
    def __init__(self):
        self._definitions = {}

    def register(self, definition: ToolDefinition):
        if definition.name in self._definitions:
            raise ValueError('Duplicate tool name')
        if any(not 1000 <= value <= 24000 for value in
               [definition.result_max_bytes, *definition.operation_result_max_bytes.values()]):
            raise ValueError('Tool result projection must be between 1000 and 24000 bytes')
        from .budget import estimate
        proposed=[*self.definitions(),definition]
        if estimate([{'name':d.name,'description':d.description,'parameters':d.input_schema} for d in proposed])>=8000:
            raise ValueError('Tool definitions exceed startup schema budget')
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
            return None, ToolResult.failure('INVALID_ARGUMENT', 'Tool arguments failed validation',
                fields=[{'path': list(e['loc']), 'message': e['msg']} for e in exc.errors()])
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
            async with asyncio.timeout(timeout):
                result = await definition.handler(arguments, context)
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
        result.call_id = context.call_id
        result.effective_input = result.effective_input or arguments.model_dump(mode='json', exclude_unset=True)
        result.metrics['elapsed_ms'] = round((monotonic() - started) * 1000)
        return result
