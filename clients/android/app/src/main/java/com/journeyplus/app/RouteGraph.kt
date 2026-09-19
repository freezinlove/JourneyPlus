package com.journeyplus.app

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

data class GraphNode(
    val id: String,
    val label: String,
    var level: Int,
    val steps: MutableList<JSONObject> = mutableListOf(),
    var row: Int = 0,
)

data class GraphEdge(val from: String, val to: String, val step: JSONObject)

/** A visual projection of server-selected paths. No eligibility calculation. */
fun graphData(objects: List<JSONObject>): Pair<List<GraphNode>, List<GraphEdge>> {
    val nodes = linkedMapOf<String, GraphNode>()
    val edges = mutableListOf<GraphEdge>()
    objects.forEach { obj ->
        val route = obj.obj("data")
        val steps = route.obj("steps")
        route.optJSONArray("step_refs").strings().forEachIndexed { i, ref ->
            val step = steps.optJSONObject(ref) ?: return@forEachIndexed
            val from = step.str("from_tier_id", step.str("from", "public"))
            val to = step.str("to_tier_id", step.str("to"))
            nodes.getOrPut(from) { GraphNode(from, step.str("from", "公开申请"), i) }
            val target = nodes.getOrPut(to) { GraphNode(to, step.str("to"), i + 1) }
            target.level = maxOf(target.level, i + 1)
            if (target.steps.none { it.str("ref") == step.str("ref") }) target.steps.add(step)
            if (edges.none { it.step.str("ref") == step.str("ref") })
                edges.add(GraphEdge(from, to, step))
        }
    }
    val rows = mutableMapOf<Int, Int>()
    nodes.values.forEach { n ->
        n.row = rows.getOrDefault(n.level, 0)
        rows[n.level] = n.row + 1
    }
    return nodes.values.toList() to edges
}

fun feeLabel(step:JSONObject):String = when(step.opt("paid")) {
    true -> "付费申请"
    false -> "免费申请"
    else -> "费用待核实"
}

@Composable
fun RouteGraph(objects: List<JSONObject>, names:List<JSONObject> = emptyList(), select: (List<JSONObject>) -> Unit) {
    val (nodes, edges) = remember(objects) { graphData(objects) }
    val color = MaterialTheme.colorScheme.primary
    val line = MaterialTheme.colorScheme.outlineVariant
    val measured=remember(objects) {mutableStateMapOf<String,Int>()}
    val density=LocalDensity.current
    fun nodeHeight(n:GraphNode)=measured[n.id] ?: 74
    val levels = nodes.groupingBy {it.level}.eachCount()
    val rows = levels.values.maxOrNull() ?: 1
    val height = maxOf(290, (rows-1)*156+134)
    fun x(n:GraphNode) = if(n.level==0) 14 else 224+(n.level-1)*275
    fun y(n:GraphNode) = if(n.steps.isEmpty()) (height-((levels[n.level] ?: 1)-1)*156-nodeHeight(n))/2+n.row*156 else 36+n.row*156
    Column(Modifier.fillMaxWidth().padding(vertical=24.dp).clip(RoundedCornerShape(22.dp))
        .border(1.dp,line,RoundedCornerShape(22.dp))) {
        Text("↔  左右滑动查看路径",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(16.dp))
        Box(Modifier.fillMaxWidth().semantics {contentDescription="会籍匹配图"}.horizontalScroll(rememberScrollState())) {
            val width=(nodes.maxOfOrNull {x(it)+if(it.steps.isEmpty())126 else 168} ?: 330)+14
            Box(Modifier.size(width.dp,height.dp)) {
                Canvas(Modifier.matchParentSize()) {
                    edges.forEach {e ->
                        val a=nodes.first {it.id==e.from};val b=nodes.first {it.id==e.to}
                        val ax=(x(a)+if(a.steps.isEmpty())126 else 168).dp.toPx();val ay=(y(a)+nodeHeight(a)/2).dp.toPx()
                        val bx=x(b).dp.toPx();val by=(y(b)+nodeHeight(b)/2).dp.toPx()
                        val bend=ax+32.dp.toPx()
                        val path=Path().apply {moveTo(ax,ay);cubicTo(bend,ay,bend,ay,bend,(ay+by)/2);cubicTo(bend,by,bend,by,bx,by)}
                        drawPath(path,color,style=Stroke(1.3.dp.toPx()))
                        drawPath(Path().apply {moveTo(bx-7.dp.toPx(),by-4.dp.toPx());lineTo(bx,by);lineTo(bx-7.dp.toPx(),by+4.dp.toPx())},color,style=Stroke(1.3.dp.toPx()))
                        if(a.steps.isEmpty())drawCircle(color,3.dp.toPx(),androidx.compose.ui.geometry.Offset(ax,ay),style=Stroke(1.2.dp.toPx()))
                    }
                }
                edges.forEach {e -> val b=nodes.first {it.id==e.to}
                    Text(feeLabel(e.step),fontSize=10.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier=Modifier.offset((x(b)-52).dp,(y(b)+nodeHeight(b)/2-21).dp))
                }
                nodes.forEach {n ->
                    Surface(modifier=Modifier.offset(x(n).dp,y(n).dp).width((if(n.steps.isEmpty())126 else 168).dp).heightIn(min=74.dp).onSizeChanged {size -> measured[n.id]=with(density){size.height.toDp().value.toInt()} }
                        .then(if(n.steps.isEmpty())Modifier else Modifier.clickable {select(n.steps)}),
                        shape=RoundedCornerShape(17.dp),border=BorderStroke(1.dp,line),color=MaterialTheme.colorScheme.surface) {
                        Row(Modifier.padding(horizontal=13.dp,vertical=14.dp),verticalAlignment=Alignment.CenterVertically) {
                            val name=names.firstOrNull { "${it.str("program")} ${it.str("tier")}"==n.label }
                            Column(Modifier.weight(1f)) {
                                Text(name?.str("program") ?: n.label,fontSize=13.sp,lineHeight=19.sp)
                                if(name!=null) Text(name.str("tier"),fontSize=12.sp,lineHeight=18.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=5.dp))
                            }
                            if(n.steps.isNotEmpty())Text("↗",fontSize=17.sp,color=color)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PresentationView(p: JSONObject, m: JourneyModel, reference: String) {
    var steps by remember { mutableStateOf<List<JSONObject>?>(null) }
    var selected by remember { mutableStateOf<JSONObject?>(null) }
    var names by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    LaunchedEffect(reference) {
        m.feedback(reference)
        if(p.items("blocks").any {it.str("type")=="route_graph"}) {
            try { names=m.graphCatalog() } catch(e:kotlinx.coroutines.CancellationException) {throw e} catch(_:Exception) { }
        }
    }
    Column {
        if(p.str("answer").isNotBlank()) MessageText(p.str("answer"), m::readActivity)
        p.items("blocks").forEach { b ->
            if (b.str("title").isNotBlank()) Section(b.str("title"), b.str("reason"))
            val objects = b.obj("payload").items("objects")
            if (b.str("type") == "route_graph") {
                RouteGraph(objects,names) {
                    steps = it
                    it.firstOrNull()?.let { step -> m.focus(reference, step.str("ref")) }
                }
                OutlinedButton(
                    onClick = { m.send("帮我查看这些会籍匹配的申请经验", objects.map { it.str("ref") }) },
                    enabled = !m.busy,
                ) {
                    Text("查看申请经验", fontSize = 12.sp)
                }
            } else if (b.str("type") == "mapping_table") {
                objects.forEach { o -> MappingMatrix(o.obj("data")) }
            } else
                objects.forEach { o ->
                    val d = o.obj("data")
                    OutlinedCard(
                        onClick = {
                            if (d.has("activity_ref"))
                                m.readActivity(d.str("activity_ref"), d.str("version_ref"))
                            else if (d.has("ref") && d.has("version_ref"))
                                m.readActivity(d.str("ref"), d.str("version_ref"))
                            else if (d.has("step_refs"))
                                steps =
                                    d.optJSONArray("step_refs").strings().map {
                                        d.obj("steps").obj(it)
                                    }
                            else selected = d
                        },
                        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(d.str("name", d.str("title", d.str("to", "资料详情"))) + " ↗")
                            Text(
                                d.obj("card")
                                    .str("summary", d.str("text", d.str("evidence_excerpt"))),
                                fontSize = 14.sp,
                            )
                            if (b.str("type") == "comparison")
                                Text(
                                    "${d.optInt("step_count")} 步 · " + feeLabel(d)
                                )
                        }
                    }
                }
            b.obj("payload").items("research").forEach { r ->
                TextButton(onClick = { selected = r.obj("data") }) { Text("公开申请经验 ↗") }
            }
        }
        p.items("next_steps").forEach { n ->
            OutlinedButton(
                onClick = { m.send(n.str("message"), n.optJSONArray("subject_refs").strings()) },
                enabled = !m.busy,
            ) {
                Text(n.str("label"))
            }
        }
    }
    if (steps != null)
        ModalBottomSheet(onDismissRequest = { steps = null }) {
            Column(Modifier.padding(24.dp).verticalScroll(rememberScrollState())) {
                Title("申请路径")
                steps!!.forEach { step -> StepView(step, m) { steps = null } }
            }
        }
    if (selected != null)
        ModalBottomSheet(onDismissRequest = { selected = null }) {
            Column(Modifier.padding(24.dp).verticalScroll(rememberScrollState())) {
                Title(selected!!.str("name", selected!!.str("title", "资料详情")))
                Text(
                    readable(
                        selected!!.opt("text")
                            ?: selected!!.opt("reports")
                            ?: selected!!.opt("facts")
                            ?: selected
                    )
                )
                ExternalLink(selected!!.str("url"))
            }
        }
}

@Composable
fun StepView(step: JSONObject, m: JourneyModel, close: () -> Unit) {
    var detail by remember(step) { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf("") }
    LaunchedEffect(step) {
        try {
            detail =
                m.api.call(
                    "/v2/activities/${step.str("activity_ref")}?version_ref=${step.str("version_ref")}&view=path_detail"
                ) as JSONObject
        } catch (e: Exception) {
            error = e.message.orEmpty()
        }
    }
    Section(
        step.str("from", "公开申请") + " → " + step.str("to"),
        feeLabel(step),
    )
    ErrorText(error)
    detail?.optJSONArray("action_links").strings().forEach { ExternalLink(it, "申请入口") }
    TextButton(
        onClick = {
            close()
            m.readActivity(step.str("activity_ref"), step.str("version_ref"))
        }
    ) {
        Text("查看对应版本简报 ↗")
    }
}
