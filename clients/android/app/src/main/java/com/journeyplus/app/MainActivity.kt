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
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
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
import kotlinx.coroutines.flow.first
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
    val targetScheme =
        if (dark)
            darkColorScheme(
                primary = Color(0xffa2c8eb), onPrimary=Color(0xff15191e),
                onSurfaceVariant = Color(0xffb2bdc9), surfaceVariant = Color(0xff262d36),
                background = Color(0xff15191e),
                surface = Color(0xff1e242c),
                onSurface = Color(0xffedf1f5),
                onBackground = Color(0xffedf1f5),
                outlineVariant = Color(0xff333d48),
            )
        else
            lightColorScheme(
                primary = Color(0xff294f73), onPrimary=Color.White,
                onSurfaceVariant = Color(0xff5a6573), surfaceVariant = Color(0xffeceeec),
                background = Color(0xfff7f7f4),
                surface = Color.White,
                onSurface = Color(0xff202832),
                onBackground = Color(0xff202832),
                outlineVariant = Color(0xffdde2e3),
            )
    @Composable fun tint(color:Color):Color = androidx.compose.animation.animateColorAsState(color,
        androidx.compose.animation.core.tween(200),label="theme").value
    val scheme=targetScheme.copy(primary=tint(targetScheme.primary),background=tint(targetScheme.background),
        surface=tint(targetScheme.surface),onSurface=tint(targetScheme.onSurface),onSurfaceVariant=tint(targetScheme.onSurfaceVariant),
        surfaceVariant=tint(targetScheme.surfaceVariant),outlineVariant=tint(targetScheme.outlineVariant))
    MaterialTheme(
        colorScheme = scheme,
        typography = Typography(
            bodyLarge = androidx.compose.ui.text.TextStyle(fontSize=15.sp,lineHeight=27.sp,letterSpacing=0.sp),
            bodyMedium = androidx.compose.ui.text.TextStyle(fontSize=14.sp,lineHeight=25.sp,letterSpacing=0.sp),
            labelLarge = androidx.compose.ui.text.TextStyle(fontSize=13.sp,fontWeight=FontWeight.Medium,letterSpacing=0.sp),
        ),
        shapes =
            Shapes(
                extraSmall = RoundedCornerShape(12.dp),
                small = RoundedCornerShape(14.dp),
                medium = RoundedCornerShape(18.dp),
                large = RoundedCornerShape(26.dp),
                extraLarge = RoundedCornerShape(28.dp),
            ),
        content = { CompositionLocalProvider(
            LocalContentColor provides scheme.onSurface,
            LocalTextStyle provides androidx.compose.ui.text.TextStyle(fontSize=14.sp,letterSpacing=0.sp,
                platformStyle=androidx.compose.ui.text.PlatformTextStyle(includeFontPadding=false))
        ) { content() } },
    )
}

@Composable
fun JourneyApp(m: JourneyModel) {
    Box(Modifier.fillMaxSize()) {
        AmbientBackground(m.dark)
        if (m.identity == null) {
            Login(m)
            return@Box
        }
        BackHandler(m.page != "chat") { if (m.page == "news") m.page = "chat" else m.back() }
        Box(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().imePadding()) {
            key(m.page) {
                Box(Modifier.fillMaxSize().pageEntrance()) {
                    when (m.page) {
                        "chat" -> ChatScreen(m)
                        "news" -> NewsScreen(m)
                        "holdings" -> HoldingsScreen(m)
                        "reader" -> BriefScreen(m)
                    }
                }
            }
            val statusHeight=WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
            Box(
                Modifier.fillMaxWidth()
                    .offset(y=-statusHeight)
                    .height(86.dp+statusHeight)
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
            val secondary = m.page in listOf("reader", "holdings")
            Box(Modifier.fillMaxWidth().padding(horizontal=15.dp, vertical=8.dp).height(44.dp)) {
                NavigationButton(if(secondary) "back" else "account", if(secondary) "返回" else "我的会籍",
                    selected=secondary, modifier=Modifier.align(Alignment.CenterStart)) {
                    if(secondary) m.back() else m.go("holdings")
                }
                if(!secondary) Row(Modifier.align(Alignment.Center).clip(RoundedCornerShape(28.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant).padding(3.dp), horizontalArrangement=Arrangement.spacedBy(4.dp)) {
                    NavigationButton("chat", "对话", m.page=="chat", Modifier.size(width=48.dp,height=38.dp)) { m.page="chat" }
                    NavigationButton("news", "会籍新闻", m.page=="news", Modifier.size(width=48.dp,height=38.dp)) { m.go("news") }
                }
                if(m.page=="chat") NavigationButton("new","新对话",modifier=Modifier.align(Alignment.CenterEnd)) { m.fresh() }
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
        JourneyIcon("brand",Modifier.size(42.dp),MaterialTheme.colorScheme.primary)
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
        fontSize = 26.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(bottom = 24.dp),
    )
}

@Composable
fun NewsScreen(m: JourneyModel) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 84.dp, bottom = 50.dp),
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
                Text(a.str("name"), fontSize = 18.sp, fontWeight = FontWeight.Medium)
                Text(
                    a.obj("card").str("summary"),
                    fontSize = 13.sp,
                    lineHeight = 24.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 10.dp),
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
        contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 84.dp, bottom = 50.dp),
    ) {
        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("我的会籍", fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
                Button(
                    shape = RoundedCornerShape(15.dp),
                    onClick = {
                        editing = null
                        show = true
                    }
                ) {
                    Text("＋ 添加会籍", fontSize=12.sp)
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
                        androidx.compose.ui.text.buildAnnotatedString {
                            append(h.str("program_display_name")); append("  ")
                            pushStyle(androidx.compose.ui.text.SpanStyle(color=MaterialTheme.colorScheme.primary,fontWeight=FontWeight.Normal))
                            append(h.str("tier_display_name")); pop()
                        },
                        fontWeight = FontWeight.Medium,
                    )
                    Text(
                        h.str("valid_until").let { if (it.isBlank()) "有效期未设置" else "有效至 $it" },
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
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
            HorizontalDivider(color=MaterialTheme.colorScheme.outlineVariant)
            Row(
                Modifier.fillMaxWidth().padding(vertical = 20.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("外观",fontSize=14.sp)
                Row(Modifier.clip(RoundedCornerShape(24.dp)).background(MaterialTheme.colorScheme.surfaceVariant).padding(4.dp)) {
                    listOf(false to "浅色", true to "深色").forEach { (dark, label) ->
                        Text(label, fontSize=13.sp, modifier=Modifier.clip(RoundedCornerShape(20.dp))
                            .background(if(m.dark==dark) MaterialTheme.colorScheme.surface else Color.Transparent)
                            .clickable {m.theme(dark)}.padding(horizontal=16.dp,vertical=9.dp))
                    }
                }
            }
            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                TextButton(onClick = m::logout) { Text("退出登录",color=MaterialTheme.colorScheme.onSurfaceVariant) }
                Text(m.identity?.str("username").orEmpty(),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
            }
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
    val shownLengths = m.displayedLengths
    fun pendingTexts()=m.messages.filter {it.str("id") in m.liveMessages}.map {msg ->
        msg.str("id") to msg.items("content").filter {it.str("type")=="text"}.joinToString("\n") {it.str("text")}
    }.filter {(id,text)->text.length>(shownLengths[id] ?: 0)}
    LaunchedEffect(Unit) {
        while(true) {
            snapshotFlow {pendingTexts()}.first {it.isNotEmpty()}
            while(pendingTexts().isNotEmpty()) {
                kotlinx.coroutines.delay(13)
                pendingTexts().forEach {(id,text)->
                    val at=shownLengths[id] ?: 0
                    shownLengths[id]=(at+if(Character.isHighSurrogate(text[at]) && at+1<text.length) 2 else 1).coerceAtMost(text.length)
                }
            }
        }
    }
    val revealing = m.messages.any {msg -> msg.str("id") in m.liveMessages &&
        msg.items("content").filter {it.str("type")=="text"}.joinToString("\n") {it.str("text")}.length > (shownLengths[msg.str("id")] ?: 0) }
    val empty = m.messages.none { it.str("role") != "tool" } && !m.busy
    var composerHeight by remember { mutableIntStateOf(54) }
    val density = androidx.compose.ui.platform.LocalDensity.current
    LaunchedEffect(m.messages, m.progress, shownLengths.values.toList()) {
        val last = list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
        if(!list.isScrollInProgress && last >= list.layoutInfo.totalItemsCount - 3 && list.layoutInfo.totalItemsCount > 0)
            list.scrollToItem(list.layoutInfo.totalItemsCount - 1)
    }
    Box(Modifier.fillMaxSize()) {
        if(!empty) LazyColumn(state=list, modifier=Modifier.fillMaxSize(),
            contentPadding=PaddingValues(start=20.dp,end=20.dp,top=84.dp,bottom=(composerHeight+32).dp)) {
            item { if(!m.workspace?.str("next_cursor").isNullOrBlank()) TextButton(onClick=m::earlier) { Text("加载更早消息") } }
            items(m.messages,key={it.str("id")}) { msg ->
                val text = msg.items("content").filter { it.str("type")=="text" }.joinToString("\n") {it.str("text")}
                val refs = msg.obj("attachments").optJSONArray("presentation_refs").strings()
                val user = msg.str("role")=="user"
                val visible = text.isNotBlank() || (refs.isNotEmpty() && !m.busy && !revealing)
                if(visible) Column(Modifier.fillMaxWidth().padding(bottom=28.dp), horizontalAlignment=if(user) Alignment.End else Alignment.Start) {
                    if(user) Text(text,fontSize=14.sp,lineHeight=24.sp,
                        modifier=Modifier.widthIn(max=330.dp).clip(RoundedCornerShape(22.dp,22.dp,6.dp,22.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant).padding(horizontal=17.dp,vertical=13.dp))
                    else {
                        if(text.isNotBlank()) {
                            Row(verticalAlignment=Alignment.CenterVertically,modifier=Modifier.padding(bottom=12.dp),horizontalArrangement=Arrangement.spacedBy(9.dp)) {
                                JourneyIcon("brand",Modifier.size(17.dp),MaterialTheme.colorScheme.primary)
                                Text("JourneyPlus",fontSize=12.sp,fontWeight=FontWeight.SemiBold)
                            }
                            MessageText(if(msg.str("id") in m.liveMessages) text.take(shownLengths[msg.str("id")] ?: 0) else text,m::readActivity)
                        }
                        if(!m.busy && !revealing) refs.forEach { ref -> m.artifacts[ref]?.let { PresentationView(it,m,ref) } }
                    }
                    msg.obj("attachments").items("operations").forEach { Text(it.str("summary"),fontSize=13.sp) }
                }
            }
            item {
                if(m.busy && m.progress.isNotBlank()) ProcessingStatus(m.progress)
                ErrorText(m.error)
                if(m.error.isNotBlank()) TextButton(onClick={m.task {m.refreshWorkspace()}}) { Text("重新连接") }
            }
        }
        if(!empty) Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(90.dp)
            .background(Brush.verticalGradient(listOf(Color.Transparent, MaterialTheme.colorScheme.background))))
        Column(Modifier.align(if(empty) Alignment.Center else Alignment.BottomCenter)
            .padding(horizontal=13.dp,vertical=14.dp).fillMaxWidth(),horizontalAlignment=Alignment.CenterHorizontally) {
            if(empty) {
                Text("想用你的会籍，开启怎样的下一程？", fontSize=23.sp, lineHeight=33.sp,fontWeight=FontWeight.Medium,
                    textAlign=androidx.compose.ui.text.style.TextAlign.Center,modifier=Modifier.padding(horizontal=12.dp).padding(bottom=28.dp))
                ErrorText(m.error)
            }
            Surface(Modifier.fillMaxWidth().onSizeChanged { composerHeight=with(density){it.height.toDp().value.toInt()} },
                shape=RoundedCornerShape(27.dp),border=BorderStroke(1.dp,MaterialTheme.colorScheme.outlineVariant),color=MaterialTheme.colorScheme.surface) {
                Row(Modifier.padding(start=18.dp,end=12.dp,top=9.dp,bottom=9.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                    androidx.compose.foundation.text.BasicTextField(m.draft,{if(it.length<=16000)m.draft=it},
                        enabled=m.workspace!=null && !m.initializing,modifier=Modifier.weight(1f).heightIn(min=26.dp,max=156.dp),
                        textStyle=LocalTextStyle.current.copy(color=MaterialTheme.colorScheme.onSurface,fontSize=16.sp,lineHeight=26.sp,
                            platformStyle=androidx.compose.ui.text.PlatformTextStyle(includeFontPadding=false)),
                        cursorBrush=androidx.compose.ui.graphics.SolidColor(MaterialTheme.colorScheme.onSurface),
                        keyboardOptions=KeyboardOptions(imeAction=ImeAction.Send),keyboardActions=KeyboardActions(onSend={m.send()}),
                        decorationBox={inner -> Box(contentAlignment=Alignment.CenterStart) {
                            if(m.draft.isEmpty()) Text("说说你持有的会籍，或想了解的匹配机会…",maxLines=1,
                                fontSize=16.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)
                            inner()
                        }})
                    Box(Modifier.size(33.dp).clip(androidx.compose.foundation.shape.CircleShape)
                        .background(MaterialTheme.colorScheme.onSurface)
                        .clickable(enabled=m.busy || (!m.initializing && m.workspace!=null && m.draft.isNotBlank())) {if(m.busy)m.stop() else m.send()}
                        .semantics { contentDescription=if(m.busy) "停止回答" else "发送" },contentAlignment=Alignment.Center) {
                        JourneyIcon(if(m.busy) "stop" else "send",Modifier.size(22.dp),MaterialTheme.colorScheme.surface)
                    }
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
fun Section(title: String, body: String) {
    Column(Modifier.padding(top = 28.dp, bottom = 12.dp)) {
        Text(title, fontSize = 17.sp, fontWeight = FontWeight.Medium)
        if (body.isNotBlank())
            Text(body, lineHeight = 26.sp, modifier = Modifier.padding(top = 12.dp))
    }
}
