

def test_route_projection_reserves_large_coverage_without_erasing_retained_rows():
    from journeyplus.agent.harness.contracts import ToolResult
    from journeyplus.agent.harness.context import bounded_result
    from journeyplus.agent.tools.projection import trim_for
    rows=[{'ref':f'artifact:routes#route:{i}','path':['Source','Target'],'condition':'x'*950} for i in range(10)]
    original=ToolResult(status='PARTIAL',data={'candidates':rows,'route_refs':[r['ref'] for r in rows]},
        next_cursor='artifact:routes|10',coverage={'complete':False,'returned':10,'total':23,
            'scope_description':'published-source-scope '*35,'omissions':['additional_candidates']})
    view=bounded_result(original,'artifact:full-result',12000,trim=trim_for('routes.evaluate'))
    assert 0<len(view.data['candidates'])<10
    assert view.data['route_refs']==[r['ref'] for r in view.data['candidates']]
    assert len(view.model_dump_json().encode())<=12000
    assert view.coverage['full_result_ref']=='artifact:full-result'
    assert view.coverage['source_next_cursor']=='artifact:routes|10'
    assert view.next_cursor is None  # Retrieve omitted rows before advancing.
    assert len(original.data['candidates'])==10
