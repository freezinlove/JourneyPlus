package com.journeyplus.app

import androidx.compose.animation.core.animateFloat
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.composed
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.*
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp

/** Same 24-unit paths as clients/web/src/Icons.tsx, not Material substitutes. */
@Composable
fun JourneyIcon(name: String, modifier: Modifier = Modifier.size(22.dp), color: Color = MaterialTheme.colorScheme.onSurfaceVariant) {
    val paths = when(name) {
        "brand" -> listOf("M16.8 7.2L14.1 14.1L7.2 16.8L9.9 9.9Z")
        "chat" -> listOf("M20 11.5a8 8 0 0 1-8 8H5l-3 2v-10a9 9 0 0 1 18 0Z", "M7 10h8M7 14h5")
        "news" -> listOf("M7 3h10a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3Z", "M8 8h8M8 12h8M8 16h5")
        "account" -> listOf("M5 21v-2a7 7 0 0 1 14 0v2")
        "back" -> listOf("M14 5l-7 7 7 7")
        "new" -> listOf("M13 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-7", "M16 3l5 5M10 14l1-4 7-7 3 3-7 7-4 1Z")
        "send" -> listOf("M12 19V5M5 12l7-7 7 7")
        "stop" -> listOf("M7 7h10v10H7Z")
        "down" -> listOf("M6 9l6 6 6-6")
        else -> listOf("M9 6l6 6-6 6")
    }
    val shapes = remember(paths) { paths.map { PathParser().parsePathString(it).toPath() } }
    Canvas(modifier) {
        scale(size.width/24f, size.height/24f, Offset.Zero) {
            val stroke = Stroke(if(name == "brand") 1.5f else 1.65f, cap=StrokeCap.Round, join=StrokeJoin.Round)
            if(name == "brand") drawCircle(color,10.25f,Offset(12f,12f),style=stroke)
            if(name == "account") drawCircle(color,3.5f,Offset(12f,8f),style=stroke)
            shapes.forEach { drawPath(it,color,style=stroke) }
        }
    }
}

@Composable
fun NavigationButton(name: String, label: String, selected: Boolean = false, modifier: Modifier = Modifier, action: () -> Unit) {
    val palette = MaterialTheme.colorScheme
    Box(modifier.size(44.dp).clip(CircleShape).background(if(selected) palette.surface else Color.Transparent)
        .clickable(onClick=action).semantics { contentDescription=label }, contentAlignment=androidx.compose.ui.Alignment.Center) {
        JourneyIcon(name,color=if(selected) palette.primary else palette.onSurfaceVariant)
    }
}

/** Fixed corner light, shared across all pages, with no blur or animation. */
@Composable
fun AmbientBackground(dark: Boolean) {
    val base = MaterialTheme.colorScheme.background
    Canvas(Modifier.fillMaxSize()) {
        drawRect(base)
        scale(size.width*.65f,size.height*.65f,Offset.Zero) {
            drawCircle(Brush.radialGradient(listOf(if(dark) Color(0x4031475e) else Color(0x80dce8f0),Color.Transparent),Offset.Zero,1f),1f,Offset.Zero)
        }
        val corner=Offset(size.width,size.height)
        scale(size.width*.55f,size.height*.60f,corner) {
            drawCircle(Brush.radialGradient(listOf(if(dark) Color(0x26343435) else Color(0x5ce8e1d6),Color.Transparent),corner,1f),1f,corner)
        }
    }
}

/** The prototype's 220 ms, 5 dp entrance; Compose respects system animation scale. */
fun Modifier.pageEntrance(): Modifier = composed {
    val progress = remember { androidx.compose.animation.core.Animatable(0f) }
    LaunchedEffect(Unit) { progress.animateTo(1f,androidx.compose.animation.core.tween(220)) }
    this.graphicsLayer { alpha=.6f+.4f*progress.value; translationY=5.dp.toPx()*(1f-progress.value) }
}

@Composable
fun ProcessingStatus(text:String) {
    val transition=androidx.compose.animation.core.rememberInfiniteTransition(label="processing")
    val opacity by transition.animateFloat(.35f,1f,androidx.compose.animation.core.infiniteRepeatable(
        androidx.compose.animation.core.tween(700),androidx.compose.animation.core.RepeatMode.Reverse),label="pulse")
    Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(9.dp),modifier=Modifier.padding(bottom=28.dp)) {
        Box(Modifier.size(7.dp).graphicsLayer {alpha=opacity}.clip(CircleShape).background(MaterialTheme.colorScheme.onSurfaceVariant))
        Text(text,fontSize=androidx.compose.ui.unit.TextUnit(14f,androidx.compose.ui.unit.TextUnitType.Sp),color=MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
