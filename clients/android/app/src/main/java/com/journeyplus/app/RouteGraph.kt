package com.journeyplus.app

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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

@Composable
fun RouteGraph(objects: List<JSONObject>, select: (List<JSONObject>) -> Unit) {
    val (nodes, edges) = remember(objects) { graphData(objects) }
    val color = MaterialTheme.colorScheme.primary
    Column(
        Modifier.fillMaxWidth()
            .padding(vertical = 18.dp)
            .clip(RoundedCornerShape(22.dp))
            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(22.dp))
    ) {
        Text("↔  左右滑动查看路径", fontSize = 12.sp, modifier = Modifier.padding(16.dp))
        Box(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
            val width = ((nodes.maxOfOrNull { it.level } ?: 0) * 252 + 208).dp
            val height = ((nodes.maxOfOrNull { it.row } ?: 0) * 128 + 124).dp
            Box(Modifier.size(width, height)) {
                Canvas(Modifier.matchParentSize()) {
                    edges.forEach { e ->
                        val a = nodes.first { it.id == e.from }
                        val b = nodes.first { it.id == e.to }
                        val x = (a.level * 252 + 192).dp.toPx()
                        val y = (a.row * 128 + 54).dp.toPx()
                        val tx = (b.level * 252 + 16).dp.toPx()
                        val ty = (b.row * 128 + 54).dp.toPx()
                        val p =
                            Path().apply {
                                moveTo(x, y)
                                cubicTo(x + 40.dp.toPx(), y, tx - 40.dp.toPx(), ty, tx, ty)
                            }
                        drawPath(p, color, style = Stroke(1.3.dp.toPx()))
                    }
                }
                edges.forEach { e ->
                    val a = nodes.first { it.id == e.from }
                    val b = nodes.first { it.id == e.to }
                    if (e.step.has("paid"))
                        Text(
                            if (e.step.optBoolean("paid")) "付费" else "免费",
                            fontSize = 10.sp,
                            modifier =
                                Modifier.offset(
                                    ((a.level * 252 + 192 + b.level * 252 + 16) / 2 - 12).dp,
                                    ((a.row * 128 + 54 + b.row * 128 + 54) / 2 - 20).dp,
                                ),
                        )
                }
                nodes.forEach { n ->
                    Surface(
                        modifier =
                            Modifier.offset((n.level * 252 + 16).dp, (n.row * 128 + 16).dp)
                                .width(176.dp)
                                .heightIn(min = 76.dp)
                                .then(
                                    if (n.steps.isEmpty()) Modifier
                                    else Modifier.clickable { select(n.steps) }
                                ),
                        shape = RoundedCornerShape(17.dp),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        color = MaterialTheme.colorScheme.surface,
                    ) {
                        Row(
                            Modifier.padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(n.label, fontSize = 13.sp, modifier = Modifier.weight(1f))
                            if (n.steps.isNotEmpty()) Text("↗", color = color)
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
    LaunchedEffect(reference) { m.feedback(reference) }
    Column {
        p.items("blocks").forEach { b ->
            if (b.str("title").isNotBlank()) Section(b.str("title"), b.str("reason"))
            val objects = b.obj("payload").items("objects")
            if (b.str("type") == "route_graph") {
                RouteGraph(objects) {
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
                objects.forEach { o ->
                    val d = o.obj("data")
                    d.items("options")
                        .flatMap { it.items("mappings") }
                        .forEach { mapping ->
                            val tiers =
                                mapping.optJSONArray("from_tiers")
                                    ?: mapping.optJSONArray("source_tiers")
                            Section(
                                mapping.str("from_program", mapping.str("source_program")),
                                tiers.strings().joinToString("、") +
                                    " → " +
                                    mapping.str("to_tier", mapping.str("target_tier")),
                            )
                            val notes = JSONObject(mapping.toString())
                            listOf(
                                    "ref",
                                    "from_program",
                                    "source_program",
                                    "from_tiers",
                                    "source_tiers",
                                    "to_program",
                                    "to_tier",
                                    "target_tier",
                                )
                                .forEach { notes.remove(it) }
                            val note = readable(notes)
                            if (note.isNotBlank()) Text(note, fontSize = 13.sp)
                            HorizontalDivider(Modifier.padding(vertical = 12.dp))
                        }
                }
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
                                    "${d.optInt("step_count")} 步 · " +
                                        if (d.optBoolean("paid")) "付费" else "免费"
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
        if (!step.has("paid")) "费用待确认" else if (step.optBoolean("paid")) "付费申请" else "免费申请",
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
