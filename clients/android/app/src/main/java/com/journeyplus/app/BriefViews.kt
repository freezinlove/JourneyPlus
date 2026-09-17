package com.journeyplus.app

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.constrainWidth
import androidx.compose.ui.unit.constrainHeight
import org.json.JSONObject

@Composable
fun BriefScreen(m: JourneyModel) {
    val d=m.detail
    LazyColumn(Modifier.fillMaxSize(), contentPadding=PaddingValues(start=22.dp,end=22.dp,top=84.dp,bottom=50.dp)) {
        item {
            ErrorText(m.error)
            if(d==null) Text(if(m.error.isEmpty()) "正在读取简报…" else "读取未完成",fontSize=14.sp)
            else {
                Text("${d.str("program")} / 会籍简报",fontSize=10.sp,letterSpacing=1.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                Text(d.obj("brief").str("title",d.str("program")),fontSize=28.sp,lineHeight=42.sp,letterSpacing=(-.7).sp,fontWeight=FontWeight.Medium,fontFamily=FontFamily.Serif,
                    modifier=Modifier.padding(top=16.dp,bottom=15.dp))
                Text(d.obj("brief").str("summary",d.str("summary")),fontSize=14.sp,lineHeight=25.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                Row(Modifier.padding(top=28.dp,bottom=24.dp),horizontalArrangement=Arrangement.spacedBy(24.dp)) {
                    Column { Text("付费情况",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant); Text(d.obj("fee").str("label","费用待确认"),fontSize=12.sp,modifier=Modifier.padding(top=7.dp)) }
                    Column { Text("简报更新于（北京时间）",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant); Text(beijingDate(d.str("brief_updated_at")),fontSize=12.sp,modifier=Modifier.padding(top=7.dp)) }
                }
                HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant)
                Section("和我的关系","")
                if(m.relationshipError.isNotBlank()) ErrorText(m.relationshipError) else RelationCards(m.relationship)
                Section("申请入口","")
                val handler=LocalUriHandler.current
                val links=d.optJSONArray("action_links").strings().filter {it.startsWith("https://") || it.startsWith("http://")}.distinct()
                links.forEachIndexed {i,url ->
                    Surface(onClick={handler.openUri(url)},shape=RoundedCornerShape(15.dp),color=MaterialTheme.colorScheme.primary,
                        contentColor=MaterialTheme.colorScheme.background,modifier=Modifier.padding(bottom=8.dp)) {
                        Text("前往申请页面${if(links.size>1) " ${i+1}" else ""}　↗",fontSize=13.sp,fontWeight=FontWeight.SemiBold,modifier=Modifier.padding(horizontal=20.dp,vertical=13.dp))
                    }
                }
                if(links.isEmpty()) Text("暂无申请入口。",fontSize=14.sp)
                CollapsibleTable("会籍匹配表",d.str("opportunity_id")) { MappingMatrix(d) }
                CollapsibleTable("价格表",d.str("opportunity_id")) { PriceMatrix(d) }
                Section("原文链接","")
                d.optJSONArray("source_links").strings().distinct().forEach { url ->
                    HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant)
                    Row(Modifier.fillMaxWidth().clickable {handler.openUri(url)}.padding(vertical=15.dp),horizontalArrangement=Arrangement.SpaceBetween) {
                        Text(when {url.contains("/faq")->"官方 FAQ";url.contains("/terms")->"官方条款";else->"官方活动页"},fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,textDecoration=androidx.compose.ui.text.style.TextDecoration.Underline)
                        Text("↗",fontSize=13.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}
fun beijingDate(value:String):String = runCatching {
    java.time.Instant.parse(value).atZone(java.time.ZoneId.of("Asia/Shanghai")).format(java.time.format.DateTimeFormatter.ofPattern("yyyy/M/d HH:mm"))
}.getOrDefault(if(value.isBlank()) "尚未生成" else value.take(10))

@Composable
fun RelationCards(data:JSONObject?) {
    val labels=data?.optJSONArray("path_labels").strings()
    if(labels.size<2) {
        Surface(shape=RoundedCornerShape(18.dp),border=BorderStroke(1.dp,MaterialTheme.colorScheme.outlineVariant),color=MaterialTheme.colorScheme.surface) {
            Text(data?.str("text") ?: "正在查看与你的会籍的关系…",fontSize=14.sp,lineHeight=25.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.fillMaxWidth().padding(18.dp))
        }
    } else {
        FitRelationship {
        Row(verticalAlignment=Alignment.CenterVertically) {
            labels.forEachIndexed {i,label ->
                if(i>0) Text("→",color=MaterialTheme.colorScheme.primary,fontSize=22.sp,modifier=Modifier.padding(horizontal=12.dp))
                Surface(shape=RoundedCornerShape(18.dp),border=BorderStroke(1.dp,MaterialTheme.colorScheme.outlineVariant),color=MaterialTheme.colorScheme.surface) {
                    Column(Modifier.width(170.dp).padding(18.dp)) {
                        Text(if(i==0) "我的会籍" else if(i==labels.lastIndex) "目标会籍" else "中间会籍",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(label.substringBeforeLast(" · ",label),fontSize=15.sp,fontWeight=FontWeight.Medium,modifier=Modifier.padding(top=10.dp))
                        if(label.contains(" · "))Text(label.substringAfterLast(" · "),color=MaterialTheme.colorScheme.primary,fontSize=14.sp,modifier=Modifier.padding(top=6.dp))
                    }
                }
            }
        }
        }
        Text("仍需满足对应方案的地区和其他申请条件。",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,modifier=Modifier.padding(top=12.dp))
    }
}

/** Measure at natural size, then scale the complete path and its layout height together. */
@Composable
fun FitRelationship(content:@Composable ()->Unit) {
    androidx.compose.ui.layout.Layout(content=content,modifier=Modifier.fillMaxWidth()) { measurables, constraints ->
        val child=measurables.single().measure(androidx.compose.ui.unit.Constraints())
        val scale=if(child.width==0) 1f else minOf(1f,constraints.maxWidth.toFloat()/child.width)
        layout(constraints.constrainWidth((child.width*scale).toInt()),constraints.constrainHeight(kotlin.math.ceil(child.height*scale).toInt())) {
            child.placeWithLayer(0,0) {
                scaleX=scale;scaleY=scale
                transformOrigin=androidx.compose.ui.graphics.TransformOrigin(0f,0f)
            }
        }
    }
}

@Composable
fun CollapsibleTable(title:String, identity:String, content:@Composable ()->Unit) {
    var open by remember(identity) {mutableStateOf(false)}
    Column(Modifier.padding(top=24.dp)) {
        Row(Modifier.fillMaxWidth().clickable {open=!open}.padding(vertical=6.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            JourneyIcon(if(open) "down" else "right",Modifier.size(16.dp))
            Text(title,fontSize=17.sp,fontWeight=FontWeight.Medium)
        }
        if(open) {Spacer(Modifier.height(14.dp));content()}
    }
}

@Composable
fun Matrix(headers:List<String>, rows:List<List<String>>) {
    Column(Modifier.horizontalScroll(rememberScrollState())) {
        fun width(index:Int)=if(index==0) 180.dp else 140.dp
        Row {headers.forEachIndexed {i,value -> Text(value,modifier=Modifier.width(width(i)).padding(12.dp),fontSize=11.sp,fontWeight=FontWeight.SemiBold)} }
        HorizontalDivider(Modifier.width((180+140*(headers.size-1)).dp),color=MaterialTheme.colorScheme.outlineVariant)
        rows.forEach { row ->
            Row {row.forEachIndexed {i,value -> Text(value,modifier=Modifier.width(width(i)).padding(12.dp),fontSize=12.sp,lineHeight=21.sp,color=if(i==0) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)} }
            HorizontalDivider(Modifier.width((180+140*(headers.size-1)).dp),color=MaterialTheme.colorScheme.outlineVariant)
        }
    }
}
@Composable
fun MappingMatrix(d:JSONObject) {
    val mappings=d.obj("facts").items("status_mappings").ifEmpty {d.items("options").flatMap {it.items("mappings")}}
    if(mappings.isEmpty()) {Text("原文没有可展示的会籍映射表。",fontSize=14.sp);return}
    fun tier(m:JSONObject):String {
        val raw=m.str("target_tier",m.str("to_tier","通用"))
        return d.str("target_status").split(',', '/').map {it.trim()}.firstOrNull {it.isNotBlank() && raw.endsWith(it,ignoreCase=true)} ?: raw
    }
    val targets=mappings.map {tier(it)}.distinct()
    val programs=mappings.map {it.str("source_program",it.str("from_program"))}.distinct()
    Matrix(listOf("现有会籍项目")+targets.map {"匹配至 $it"},programs.map {program -> listOf(program)+targets.map {tier ->
        mappings.filter {it.str("source_program",it.str("from_program"))==program && tier(it)==tier}.joinToString("\n") {m ->
            val names=(m.optJSONArray("source_tiers") ?: m.optJSONArray("from_tiers")).strings().distinct().joinToString("\n")
            listOf(names.ifBlank {"未说明原等级"}, when(m.str("availability")) {
                "UNAVAILABLE"->"不可用";"CONDITIONAL"->"有条件／可选";"UNKNOWN"->"可用性待确认";else->""
            },if(m.optBoolean("conflict")) "信息有冲突" else "",m.str("conditions"),m.str("conflict_note"))
                .filter {it.isNotBlank()}.distinct().joinToString("\n")
        }.ifBlank {"—"}
    }})
}
@Composable
fun PriceMatrix(d:JSONObject) {
    val routes=d.items("routes")
    val targets=routes.flatMap {it.items("prices")}.map {it.str("target_tier","通用")}.distinct()
    if(targets.isEmpty()) {Text("原文没有可展示的匹配费用表。",fontSize=14.sp);return}
    Matrix(listOf("申请方式")+targets,routes.map {r -> listOf(listOf(r.str("scope"),r.str("region"),r.str("eligibility"),r.str("cost")).filter {it.isNotBlank()}.distinct().joinToString("\n"))+targets.map {t ->
        r.items("prices").filter {it.str("target_tier","通用")==t}.joinToString("\n") {p ->
            if(!p.isNull("amount")) "${p.str("currency")} ${p.str("amount").removeSuffix(".0")}" + when(p.str("availability")) {
                "CONDITIONAL"->"\n有条件／可选费用" + p.str("raw_text").let {if(it.isNotBlank()) "：$it" else ""}
                "UNKNOWN"->"\n可用性待确认";else->""
            } else when(p.str("availability")) {"UNAVAILABLE"->"不可用";"CONDITIONAL"->"有条件";else->p.str("raw_text","费用待核实")}
        }.ifBlank {"—"}
    }})
}
