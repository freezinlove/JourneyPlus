"""Persist factual lack-of-progress observations, without choosing business actions."""

def observe(state, name, result):
    interpretation = result.data.get('result_interpretation', {})
    condition = interpretation.get('state')
    blockers = state.setdefault('blockers', {})
    if condition in {'MISSING_CONDITIONS', 'UNRESOLVED_IDENTITY'}:
        blockers[name] = interpretation
    elif condition == 'SEARCH_COMPLETED':
        blockers.pop(name, None)
    unproductive = bool(result.error or result.status in {'EMPTY', 'NOT_FOUND'} or condition in {
        'MISSING_CONDITIONS', 'UNRESOLVED_IDENTITY'})
    state['unproductive_reads'] = state.get('unproductive_reads', 0) + 1 if unproductive else 0
    if blockers:
        return ('Unresolved query conditions remain: ' + str(list(blockers.values())) +
                '. Other retrieved material does not establish user intent. Reassess the original request; '
                'ask for missing user information when absent from the conversation. Do not substitute a different deliverable.')
    if state['unproductive_reads'] >= 2:
        return ('Consecutive reads have returned no usable result. Reassess whether the gap is user intent or '
                'retrievable facts. Continue only with a concrete new basis; a clarification or scoped no-result answer is valid.')
    return None
