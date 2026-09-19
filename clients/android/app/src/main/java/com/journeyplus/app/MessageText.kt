package com.journeyplus.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.ClickableText
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Small native Markdown reader. HTML is always plain text; only HTTP(S) links open. */
@Composable
fun MessageText(text: String, openActivity: (String, String) -> Unit) {
    val uri = LocalUriHandler.current
    val color = MaterialTheme.colorScheme.primary
    Column {
        text.trim().lines().forEach { line ->
            if(line.isBlank()) { Spacer(Modifier.height(8.dp)); return@forEach }
            if(Regex("^[-*_]{3,}$").matches(line.trim())) {
                androidx.compose.material3.HorizontalDivider(Modifier.padding(vertical=8.dp),color=MaterialTheme.colorScheme.outlineVariant)
                return@forEach
            }
            val heading = line.takeWhile { it == '#' }.length
            val body =
                if (heading in 1..6) line.drop(heading).trimStart()
                else line.replace(Regex("^[-*] "), "• ")
            val annotated = buildAnnotatedString {
                val pattern = Regex("\\[([^]]+)]\\(([^)]+)\\)|\\*\\*([^*]+)\\*\\*")
                var end = 0
                pattern.findAll(body).forEach { match ->
                    append(body.substring(end, match.range.first))
                    if (match.groupValues[1].isNotEmpty()) {
                        pushStringAnnotation("URL", match.groupValues[2])
                        withStyle(SpanStyle(color = color)) { append(match.groupValues[1] + " ↗") }
                        pop()
                    } else
                        withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) {
                            append(match.groupValues[3])
                        }
                    end = match.range.last + 1
                }
                append(body.substring(end))
            }
            @Suppress("DEPRECATION")
            ClickableText(
                annotated,
                modifier =
                    Modifier.fillMaxWidth().padding(vertical = if (body.isBlank()) 5.dp else 2.dp),
                style =
                    MaterialTheme.typography.bodyLarge.copy(
                        color = MaterialTheme.colorScheme.onSurface,
                        fontSize = if (heading in 1..3) 22.sp else 15.sp,
                        lineHeight = 26.sp,
                        fontWeight = if (heading in 1..6) FontWeight.SemiBold else FontWeight.Normal,
                    ),
                onClick = { offset ->
                    annotated
                        .getStringAnnotations("URL", offset, offset)
                        .firstOrNull()
                        ?.item
                        ?.let { url ->
                            if (url.startsWith("/knowledge?") || url.startsWith("/news?")) {
                                val parsed = android.net.Uri.parse(url)
                                parsed.getQueryParameter("activity_id")?.let {
                                    openActivity(
                                        it,
                                        parsed.getQueryParameter("version_ref").orEmpty(),
                                    )
                                }
                            } else if (url.startsWith("https://") || url.startsWith("http://"))
                                runCatching { uri.openUri(url) }
                        }
                },
            )
        }
    }
}
