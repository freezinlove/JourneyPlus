package com.journeyplus.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import kotlinx.coroutines.launch
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    private val model: JourneyModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { JourneyTheme(model.dark) { JourneyApp(model) } }
    }
}

@Composable
fun JourneyTheme(dark: Boolean, content: @Composable () -> Unit) {
    val activity = LocalActivity.current
    SideEffect {
        activity?.let {
            WindowCompat.getInsetsController(it.window, it.window.decorView).apply {
                isAppearanceLightStatusBars = !dark
                isAppearanceLightNavigationBars = !dark
            }
        }
    }
    val scheme =
        if (dark)
            darkColorScheme(
                primary = Color(0xffa2c8eb),
                background = Color(0xff14171c),
                surface = Color(0xff1d2229),
                onSurface = Color(0xffedf1f5),
                onBackground = Color(0xffedf1f5),
                outlineVariant = Color(0xff39434f),
            )
        else
            lightColorScheme(
                primary = Color(0xff294f73),
                background = Color(0xfff5f6f8),
                surface = Color.White,
                onSurface = Color(0xff202832),
                onBackground = Color(0xff202832),
                outlineVariant = Color(0xffd8e0e9),
            )
    MaterialTheme(
        colorScheme = scheme,
        shapes =
            Shapes(
                extraSmall = RoundedCornerShape(12.dp),
                small = RoundedCornerShape(14.dp),
                medium = RoundedCornerShape(18.dp),
                large = RoundedCornerShape(26.dp),
                extraLarge = RoundedCornerShape(28.dp),
            ),
        content = content,
    )
}

@Composable
fun JourneyApp(m: JourneyModel) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        if (m.identity == null) {
            Login(m)
            return@Surface
        }
        BackHandler(m.page != "chat") { if (m.page == "news") m.page = "chat" else m.back() }
        Box(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().imePadding()) {
            when (m.page) {
                "chat" -> ChatScreen(m)
                "news" -> NewsScreen(m)
                "holdings" -> HoldingsScreen(m)
                "reader" -> BriefScreen(m)
            }
            Box(
                Modifier.fillMaxWidth()
                    .height(86.dp)
                    .align(Alignment.TopCenter)
                    .background(
                        Brush.verticalGradient(
                            listOf(
                                MaterialTheme.colorScheme.background,
                                MaterialTheme.colorScheme.background.copy(alpha = 0f),
                            )
                        )
                    )
            )
            if (m.page != "chat")
                Box(
                    Modifier.fillMaxWidth()
                        .height(38.dp)
                        .align(Alignment.BottomCenter)
                        .background(
                            Brush.verticalGradient(
                                listOf(
                                    MaterialTheme.colorScheme.background.copy(alpha = 0f),
                                    MaterialTheme.colorScheme.background,
                                )
                            )
                        )
                )
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val secondary = m.page in listOf("reader", "holdings")
                IconButton(onClick = { if (secondary) m.back() else m.go("holdings") }) {
                    Icon(
                        if (secondary) Icons.Outlined.ArrowBack else Icons.Outlined.PersonOutline,
                        if (secondary) "返回" else "我的会籍",
                    )
                }
                Spacer(Modifier.weight(1f))
                if (!secondary)
                    Row(
                        Modifier.clip(RoundedCornerShape(28.dp))
                            .background(MaterialTheme.colorScheme.onSurface.copy(alpha = .05f))
                            .padding(4.dp)
                    ) {
                        IconButton(
                            onClick = { m.page = "chat" },
                            modifier =
                                Modifier.clip(RoundedCornerShape(24.dp))
                                    .background(
                                        if (m.page == "chat") MaterialTheme.colorScheme.surface
                                        else Color.Transparent
                                    ),
                        ) {
                            Icon(
                                Icons.Outlined.ChatBubbleOutline,
                                "对话",
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                        IconButton(
                            onClick = { m.go("news") },
                            modifier =
                                Modifier.clip(RoundedCornerShape(24.dp))
                                    .background(
                                        if (m.page == "news") MaterialTheme.colorScheme.surface
                                        else Color.Transparent
                                    ),
                        ) {
                            Icon(
                                Icons.Outlined.Article,
                                "会籍新闻",
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                Spacer(Modifier.weight(1f))
                if (m.page == "chat")
                    IconButton(onClick = { m.fresh() }, enabled = !m.busy) {
                        Icon(Icons.Outlined.Edit, "新对话")
                    }
                else Spacer(Modifier.width(48.dp))
            }
        }
    }
}

@Composable
fun Login(m: JourneyModel) {
    var server by remember { mutableStateOf(m.api.base) }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            Icons.Outlined.Explore,
            null,
            Modifier.size(40.dp),
            tint = MaterialTheme.colorScheme.primary,
        )
        Text(
            "JourneyPlus",
            fontSize = 30.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(vertical = 24.dp),
        )
        Text("从已有会籍，找到你的下一程。", modifier = Modifier.padding(bottom = 24.dp))
        OutlinedTextField(
            username,
            { username = it },
            label = { Text("账号") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        OutlinedTextField(
            password,
            { password = it },
            label = { Text("密码") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        OutlinedTextField(
            server,
            { server = it },
            label = { Text("服务地址") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        ErrorText(m.error)
        Button(
            onClick = { m.login(server, username, password) },
            enabled = !m.checking && username.isNotBlank() && password.isNotBlank(),
            modifier = Modifier.fillMaxWidth().padding(top = 20.dp),
        ) {
            Text(if (m.checking) "正在连接…" else "登录")
        }
    }
}

@Composable
fun ErrorText(text: String) {
    if (text.isNotBlank())
        Text(
            text,
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.padding(vertical = 12.dp),
            fontSize = 14.sp,
        )
}

@Composable
fun Title(text: String) {
    Text(
        text,
        fontSize = 28.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(bottom = 24.dp),
    )
}

@Composable
fun NewsScreen(m: JourneyModel) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 96.dp, bottom = 50.dp),
    ) {
        item {
            Title("会籍新闻")
            ErrorText(m.error)
        }
        items(m.news, key = { it.str("ref") }) { a ->
            Column(
                Modifier.fillMaxWidth()
                    .clickable { m.readActivity(a.str("ref")) }
                    .padding(vertical = 24.dp)
            ) {
                Text(a.str("name"), fontSize = 19.sp, fontWeight = FontWeight.Medium)
                Text(
                    a.obj("card").str("summary"),
                    fontSize = 14.sp,
                    lineHeight = 24.sp,
                    modifier = Modifier.padding(vertical = 10.dp),
                )
                Text(
                    a.str("updated_at").take(10) + "  ↗",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        }
        item {
            if (m.loadingNews) Text("正在读取新闻…")
            else if (m.moreNews)
                TextButton(onClick = { m.task { m.loadNews(false) } }) { Text("加载更多") }
            else if (m.news.isEmpty()) Text("暂时没有已发布新闻")
        }
    }
}

@Composable
fun HoldingsScreen(m: JourneyModel) {
    var editing by remember { mutableStateOf<JSONObject?>(null) }
    var show by remember { mutableStateOf(false) }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 96.dp, bottom = 50.dp),
    ) {
        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("我的会籍", fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
                Button(
                    onClick = {
                        editing = null
                        show = true
                    }
                ) {
                    Text("＋ 添加")
                }
            }
            ErrorText(m.error)
            Spacer(Modifier.height(28.dp))
        }
        items(m.holdings, key = { it.str("id") }) { h ->
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(
                Modifier.fillMaxWidth().padding(vertical = 24.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        h.str("program_display_name") + "  " + h.str("tier_display_name"),
                        fontWeight = FontWeight.Medium,
                    )
                    Text(
                        h.str("valid_until").let { if (it.isBlank()) "有效期未设置" else "有效至 $it" },
                        fontSize = 12.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                TextButton(
                    onClick = {
                        editing = h
                        show = true
                    }
                ) {
                    Text("编辑")
                }
            }
        }
        item {
            if (m.holdings.isEmpty())
                Text("添加已有会籍，让每条路径从你出发。", modifier = Modifier.padding(vertical = 32.dp))
            HorizontalDivider()
            Row(
                Modifier.fillMaxWidth().padding(vertical = 20.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("深色外观")
                Switch(checked = m.dark, onCheckedChange = m::theme)
            }
            Text(m.identity?.str("username").orEmpty(), fontSize = 13.sp)
            TextButton(onClick = m::logout) { Text("退出登录") }
        }
    }
    if (show) HoldingEditor(m, editing) { show = false }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HoldingEditor(m: JourneyModel, existing: JSONObject?, close: () -> Unit) {
    var q by remember { mutableStateOf("") }
    var nodes by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var selected by remember { mutableStateOf(existing) }
    var date by remember { mutableStateOf(existing?.str("valid_until").orEmpty()) }
    var error by remember { mutableStateOf("") }
    var saving by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(q) {
        try {
            nodes = m.catalog(q)
        } catch (e: Exception) {
            error = e.message.orEmpty()
        }
    }
    ModalBottomSheet(onDismissRequest = close, containerColor = MaterialTheme.colorScheme.surface) {
        Column(Modifier.padding(24.dp).verticalScroll(rememberScrollState()).imePadding()) {
            Title(if (existing == null) "添加会籍" else "编辑会籍")
            OutlinedTextField(
                q,
                { q = it },
                label = { Text("搜索航司或酒店") },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            LazyColumn(Modifier.heightIn(max = 220.dp)) {
                items(nodes) { n ->
                    Row(
                        Modifier.fillMaxWidth().clickable { selected = n }.padding(vertical = 10.dp)
                    ) {
                        RadioButton(
                            selected =
                                selected?.str("program_key") == n.str("program_key") &&
                                    selected?.str("tier_key") == n.str("tier_key"),
                            onClick = { selected = n },
                        )
                        Text(
                            n.str("program") + " · " + n.str("tier"),
                            modifier = Modifier.align(Alignment.CenterVertically),
                        )
                    }
                }
            }
            selected?.let {
                Text(
                    "已选：" +
                        it.str("program_display_name", it.str("program")) +
                        " · " +
                        it.str("tier_display_name", it.str("tier")),
                    fontSize = 13.sp,
                )
            }
            OutlinedTextField(
                date,
                { date = it },
                label = { Text("有效期 YYYY-MM-DD（可选）") },
                modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
                singleLine = true,
            )
            ErrorText(error)
            Button(
                enabled = selected != null && !saving,
                onClick = {
                    scope.launch {
                        saving = true
                        try {
                            if (date.isNotBlank()) java.time.LocalDate.parse(date)
                            m.saveHolding(existing, selected!!, date)
                            close()
                        } catch (e: Exception) {
                            error = e.message ?: "保存失败"
                        } finally {
                            saving = false
                        }
                    }
                },
            ) {
                Text("保存")
            }
            if (existing != null)
                TextButton(onClick = { confirmDelete = true }, enabled = !saving) { Text("删除会籍") }
        }
    }
    if (confirmDelete)
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("删除这条会籍？") },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            try {
                                m.deleteHolding(existing!!)
                                close()
                            } catch (e: Exception) {
                                error = e.message.orEmpty()
                            }
                            confirmDelete = false
                        }
                    }
                ) {
                    Text("删除")
                }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("取消") } },
        )
}

@Composable
fun ChatScreen(m: JourneyModel) {
    val list = androidx.compose.foundation.lazy.rememberLazyListState()
    LaunchedEffect(m.messages, m.progress) {
        if (
            list.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let {
                it >= list.layoutInfo.totalItemsCount - 3
            } != false
        )
            list.animateScrollToItem((m.messages.size + 1).coerceAtLeast(0))
    }
    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            state = list,
            modifier = Modifier.fillMaxSize(),
            contentPadding =
                PaddingValues(start = 20.dp, end = 20.dp, top = 100.dp, bottom = 210.dp),
        ) {
            item {
                if (!m.workspace?.str("next_cursor").isNullOrBlank())
                    TextButton(onClick = m::earlier) { Text("加载更早消息") }
                if (m.messages.isEmpty()) {
                    Spacer(Modifier.height(100.dp))
                    Title("从已有会籍出发")
                    Text("告诉我你已有的会籍，或想去的下一程。")
                }
            }
            items(m.messages, key = { it.str("id") }) { msg ->
                val user = msg.str("role") == "user"
                Column(
                    Modifier.fillMaxWidth().padding(vertical = 16.dp),
                    horizontalAlignment = if (user) Alignment.End else Alignment.Start,
                ) {
                    if (!user)
                        Text(
                            "◉  JourneyPlus",
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.padding(bottom = 12.dp),
                        )
                    val text =
                        msg.items("content")
                            .filter { it.str("type") == "text" }
                            .joinToString("\n") { it.str("text") }
                    if (text.isNotBlank() && user)
                        Text(
                            text,
                            fontSize = 15.sp,
                            lineHeight = 26.sp,
                            modifier =
                                if (user)
                                    Modifier.widthIn(max = 320.dp)
                                        .clip(RoundedCornerShape(22.dp, 22.dp, 4.dp, 22.dp))
                                        .background(
                                            MaterialTheme.colorScheme.onSurface.copy(alpha = .05f)
                                        )
                                        .padding(16.dp)
                                else Modifier,
                        )
                    if (text.isNotBlank() && !user) MessageText(text, m::readActivity)
                    for (ref in
                        msg.obj("attachments").optJSONArray("presentation_refs").strings()) m
                        .artifacts[ref]
                        ?.let { PresentationView(it, m, ref) }
                    msg.obj("attachments").items("operations").forEach { Text(it.str("summary")) }
                }
            }
            item {
                if (m.progress.isNotBlank()) Text(m.progress, fontSize = 13.sp)
                ErrorText(m.error)
                if (m.error.isNotBlank())
                    TextButton(onClick = { m.task { m.refreshWorkspace() } }) { Text("重新连接") }
            }
        }
        Box(
            Modifier.align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(60.dp)
                .background(
                    Brush.verticalGradient(
                        listOf(
                            MaterialTheme.colorScheme.background.copy(alpha = 0f),
                            MaterialTheme.colorScheme.background,
                        )
                    )
                )
        )
        Surface(
            Modifier.align(Alignment.BottomCenter)
                .padding(horizontal = 14.dp, vertical = 10.dp)
                .fillMaxWidth(),
            shape = RoundedCornerShape(27.dp),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
            color = MaterialTheme.colorScheme.surface,
        ) {
            Row(
                Modifier.padding(start = 16.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                androidx.compose.foundation.text.BasicTextField(
                    value = m.draft,
                    onValueChange = { if (it.length <= 16000) m.draft = it },
                    modifier =
                        Modifier.weight(1f)
                            .heightIn(min = 36.dp, max = 156.dp)
                            .padding(vertical = 7.dp),
                    textStyle =
                        LocalTextStyle.current.copy(
                            color = MaterialTheme.colorScheme.onSurface,
                            fontSize = 15.sp,
                            lineHeight = 22.sp,
                        ),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { m.send() }),
                    decorationBox = { inner ->
                        if (m.draft.isEmpty())
                            Text(
                                "继续聊聊你想获得的会籍…",
                                fontSize = 15.sp,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .5f),
                            )
                        inner()
                    },
                )
                IconButton(
                    onClick = { if (m.busy) m.stop() else m.send() },
                    enabled = m.busy || m.draft.isNotBlank(),
                    modifier =
                        Modifier.size(38.dp)
                            .clip(RoundedCornerShape(20.dp))
                            .background(MaterialTheme.colorScheme.onSurface),
                ) {
                    Icon(
                        if (m.busy) Icons.Outlined.Stop else Icons.Outlined.ArrowUpward,
                        if (m.busy) "停止回答" else "发送",
                        tint = MaterialTheme.colorScheme.surface,
                    )
                }
            }
        }
    }
}

@Composable
fun ExternalLink(url: String, label: String = "原始资料") {
    val handler = LocalUriHandler.current
    if (url.startsWith("https://") || url.startsWith("http://"))
        TextButton(onClick = { runCatching { handler.openUri(url) } }) { Text("$label ↗") }
}

fun readable(v: Any?): String =
    when (v) {
        null,
        JSONObject.NULL -> "未提供"
        is JSONObject ->
            if (v.has("value")) readable(v.opt("value"))
            else if (v.has("raw_text")) v.str("raw_text")
            else
                v.keys()
                    .asSequence()
                    .filterNot { it.endsWith("_id") || it.endsWith("_ref") || it == "evidence" }
                    .joinToString("；") { "$it：${readable(v.opt(it))}" }
        is org.json.JSONArray -> (0 until v.length()).joinToString("；") { readable(v.opt(it)) }
        else -> v.toString()
    }

@Composable
fun BriefScreen(m: JourneyModel) {
    val d = m.detail
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 96.dp, bottom = 50.dp),
    ) {
        item {
            ErrorText(m.error)
            if (d == null) Text(if (m.error.isEmpty()) "正在读取简报…" else "读取未完成")
            else {
                Title(d.obj("brief").str("title", d.str("program")))
                Text(d.obj("brief").str("summary", d.str("summary")), lineHeight = 28.sp)
                Text(
                    d.obj("fee").str("label") + " · " + d.str("brief_updated_at").take(10),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(vertical = 18.dp),
                )
                Section("和我的关系", d.obj("relationship").str("text", "尚未计算"))
                if (d.str("lifecycle_status") in listOf("EXPIRED", "STALE", "ARCHIVED"))
                    Section(
                        "资料状态",
                        mapOf("EXPIRED" to "活动已结束", "STALE" to "资料已过期", "ARCHIVED" to "已归档")[
                                d.str("lifecycle_status")]
                            .orEmpty(),
                    )
                Text("申请入口", fontSize = 20.sp)
                d.optJSONArray("action_links").strings().forEach { ExternalLink(it, "前往申请页面") }
                val facts = d.obj("facts")
                listOf(
                        "eligibility" to "申请资格",
                        "challenge_requirements" to "挑战要求",
                        "deadline" to "截止时间",
                        "status_validity" to "会籍有效期",
                        "caveats" to "注意事项",
                    )
                    .forEach { (key, label) ->
                        if (facts.has(key)) Section(label, readable(facts.opt(key)))
                    }
                Section("会籍映射", "")
                facts.items("status_mappings").forEach { mapping ->
                    Text(
                        mapping.str("source_program") +
                            " · " +
                            mapping.optJSONArray("source_tiers").strings().joinToString("、") +
                            " → " +
                            mapping.str("target_tier"),
                        modifier = Modifier.padding(vertical = 8.dp),
                    )
                    if (mapping.str("conditions").isNotBlank())
                        Text(mapping.str("conditions"), fontSize = 13.sp)
                }
                Section("申请方式与费用", "")
                d.items("routes").forEach { r ->
                    Section(
                        r.str("scope"),
                        listOf(
                                r.str("region"),
                                r.str("eligibility"),
                                r.str("cost"),
                                r.str("conflict_note"),
                            )
                            .filter { it.isNotBlank() }
                            .joinToString("；"),
                    )
                    r.items("prices").forEach { p ->
                        Text(
                            p.str("target_tier") +
                                " · " +
                                if (p.str("availability") == "UNAVAILABLE") "不可申请"
                                else
                                    p.str("currency") +
                                        " " +
                                        p.str("amount", "费用待确认") +
                                        " " +
                                        p.str("raw_text"),
                            modifier = Modifier.padding(vertical = 8.dp),
                        )
                    }
                }
                Section("原文来源", "")
                d.optJSONArray("source_links").strings().forEach { ExternalLink(it, it) }
            }
        }
    }
}

@Composable
fun Section(title: String, body: String) {
    Column(Modifier.padding(top = 28.dp, bottom = 12.dp)) {
        Text(title, fontSize = 20.sp, fontWeight = FontWeight.Medium)
        if (body.isNotBlank())
            Text(body, lineHeight = 26.sp, modifier = Modifier.padding(top = 12.dp))
    }
}
