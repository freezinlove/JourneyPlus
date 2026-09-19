package com.journeyplus.app

import android.app.Application
import androidx.compose.runtime.*
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.net.URLEncoder
import java.util.UUID
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

class JourneyModel @JvmOverloads constructor(application: Application, bootstrap: Boolean = true) : AndroidViewModel(application) {
    val api = Api(application)
    private val prefs = application.getSharedPreferences("settings", 0)
    var dark by mutableStateOf(prefs.getBoolean("dark", false))
        private set

    var identity by mutableStateOf<JSONObject?>(null)
        private set

    var checking by mutableStateOf(true)
        private set

    var page by mutableStateOf("chat")
    var previous by mutableStateOf("chat")
    var error by mutableStateOf("")
    var progress by mutableStateOf("")
    var busy by mutableStateOf(false)
    var messages by mutableStateOf<List<JSONObject>>(emptyList())
    var workspace by mutableStateOf<JSONObject?>(null)
    var initializing by mutableStateOf(false)
    var liveMessages by mutableStateOf<Set<String>>(emptySet())
    val displayedLengths = mutableStateMapOf<String, Int>()
    var relationship by mutableStateOf<JSONObject?>(null)
    var relationshipError by mutableStateOf("")
    private var readerJob: Job? = null
    var holdings by mutableStateOf<List<JSONObject>>(emptyList())
    var news by mutableStateOf<List<JSONObject>>(emptyList())
    var moreNews by mutableStateOf(true)
    var loadingNews by mutableStateOf(false)
    var detail by mutableStateOf<JSONObject?>(null)
    var artifacts by mutableStateOf<Map<String, JSONObject>>(emptyMap())
    var draft by mutableStateOf("")
    private var stream: Job? = null
    private var runId = ""
    private var pending: JSONObject? = null

    init {
        if (bootstrap) task {
            try {
                identity = api.call("/auth/me") as JSONObject
                refreshWorkspace()

            } finally {
                checking = false
            }
        }
    }

    fun theme(value: Boolean) {
        dark = value
        prefs.edit().putBoolean("dark", value).apply()
    }

    fun task(block: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.status == 401) {
                    identity = null
                    clearUser()
                }
                error = e.message ?: "操作未完成"
            }
        }
    }

    private fun clearUser() {
        stream?.cancel()
        api.eventCall?.cancel()
        messages = emptyList()
        artifacts = emptyMap()
        holdings = emptyList()
        news = emptyList()
        workspace = null
        detail = null
        readerJob?.cancel()
        relationship = null
        relationshipError = ""
        liveMessages = emptySet()
        initializing = false
        pending = null
        busy = false
        page = "chat"
    }

    fun login(server: String, user: String, password: String) {
        task {
            error = ""
            checking = true
            try {
                api.configure(server)
                api.call("/auth/login", json("username" to user, "password" to password))
                identity = api.call("/auth/me") as JSONObject
                refreshWorkspace()

            } finally {
                checking = false
            }
        }
    }

    fun logout() {
        task {
            api.call("/auth/logout", JSONObject())
            api.clear()
            identity = null
            clearUser()
        }
    }

    suspend fun loadHoldings() {
        holdings = (api.call("/v1/status-holdings") as JSONArray).objects()
    }

    suspend fun loadNews(reset: Boolean = true) {
        if (loadingNews) return
        loadingNews = true
        try {
            val offset = if (reset) 0 else news.size
            val result = api.call("/v2/activities?view=cards&limit=20&offset=$offset") as JSONObject
            news = (if (reset) emptyList() else news) + result.items("activities")
            moreNews = result.optBoolean("has_more")
        } finally {
            loadingNews = false
        }
    }

    fun go(target: String) {
        previous = page
        page = target
        error = ""
        if (target == "news") task { loadNews() }
        if (target == "holdings") task { loadHoldings() }
    }

    fun back() {
        page = previous.takeUnless { it == "reader" || it == "holdings" } ?: "chat"
        detail = null
        readerJob?.cancel()
    }

    fun readActivity(id: String, version: String = "") {
        previous = page
        page = "reader"
        detail = null
        relationship = null
        relationshipError = ""
        error = ""
        readerJob?.cancel()
        readerJob = viewModelScope.launch {
            try {
                val suffix = if(version.isNotBlank()) "?version_ref=$version&" else "?"
                detail = api.call("/v2/activities/$id/brief${suffix}include_relationship=false") as JSONObject
                try {
                    val pinned = if(detail!!.str("source")=="STATUSMATCH_OFFICIAL") detail!!.str("opportunity_id") else version
                    relationship = api.call("/v2/activities/$id/relationship" + if(pinned.isNotBlank()) "?version_ref=$pinned" else "") as JSONObject
                } catch(e: CancellationException) { throw e }
                catch(e: Exception) { relationshipError=e.message ?: "关系读取失败" }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { error=e.message ?: "简报读取失败" }
        }
    }

    private var cachedGraphCatalog: List<JSONObject>? = null
    suspend fun graphCatalog():List<JSONObject> = cachedGraphCatalog ?: catalog("").also {cachedGraphCatalog=it}

    suspend fun catalog(q: String): List<JSONObject> =
        (api.call("/v1/membership-catalog?limit=500&q=" + URLEncoder.encode(q, "UTF-8"))
                as JSONObject)
            .items("nodes")

    suspend fun saveHolding(existing: JSONObject?, node: JSONObject, date: String) {
        api.call(
            "/v1/status-holdings" + (existing?.let { "/" + it.str("id") } ?: ""),
            json(
                "program_key" to node.str("program_key"),
                "tier_key" to node.str("tier_key"),
                "valid_until" to date.ifBlank { null },
            ),
            if (existing == null) "POST" else "PATCH",
        )
        loadHoldings()
    }

    suspend fun deleteHolding(h: JSONObject) {
        api.call("/v1/status-holdings/" + h.str("id"), method = "DELETE")
        loadHoldings()
    }

    private suspend fun hydrate() {
        val id = workspace!!.str("id")
        workspace = api.call("/v3/agent/workspaces/$id") as JSONObject
        messages = workspace!!.items("messages").filter { it.str("role") != "tool" }
        for (m in messages) for (ref in
            m.obj("attachments").optJSONArray("presentation_refs").strings()) loadPresentation(ref)
    }

    suspend fun loadPresentation(ref: String) {
        if (artifacts.containsKey(ref)) return
        val id = workspace!!.str("id")
        val result =
            api.call(
                "/v3/agent/workspaces/$id/artifacts/" +
                    ref.removePrefix("artifact:").substringBefore('#')
            ) as JSONObject
        artifacts = artifacts + (ref to result.obj("payload"))
    }

    suspend fun refreshWorkspace(fresh: Boolean = false) {
        stream?.cancel()
        api.eventCall?.cancel()
        initializing = true
        busy = false
        if(fresh) { messages=emptyList(); workspace=null; draft=""; liveMessages=emptySet() }
        try {
            workspace =
                api.call(
                    if (fresh) "/v3/agent/workspaces" else "/v3/agent/workspaces/current",
                    if (fresh) JSONObject() else null,
                ) as JSONObject
            artifacts = emptyMap()
            hydrate()
            val active = workspace!!.items("runs").firstOrNull { !ended(it.str("status")) }
            if (active != null) listen(active.str("run_id"), active.optInt("last_seq"))
            else busy = false
        } catch (e: Exception) {
            busy = false
            throw e
        } finally { initializing=false }
    }

    fun fresh() {
        if (initializing) return
        task {
            pending = null
            progress = ""
            error = ""
            refreshWorkspace(true)
        }
    }

    /** Tool-call text is progress, not a second final answer. Keep its artifacts. */
    fun visibleMessages(): List<JSONObject> {
        val lastUser = messages.indexOfLast {it.str("role")=="user"}
        val lastText = messages.indexOfLast {m -> m.str("role")=="assistant" && m.items("content").any {it.str("type")=="text" && it.str("text").isNotBlank()} }
        return messages.mapIndexed {index, m ->
            val process=m.optBoolean("progress_only") || m.items("content").any {it.str("type")=="tool_call"}
            if(process && !(busy && index>lastUser && index==lastText))
                JSONObject(m.toString()).put("content",JSONArray())
            else m
        }
    }

    fun send(text: String = draft, refs: List<String> = emptyList()) {
        if (busy || initializing || text.isBlank() || workspace == null) return
        val optimisticId="pending:"+UUID.randomUUID().toString()
        draft=""
        messages=messages+json("id" to optimisticId,"role" to "user",
            "content" to JSONArray().put(json("type" to "text","text" to text)))
        busy=true
        task {
            progress = "正在思考…"
            liveMessages = emptySet()
            displayedLengths.clear()
            error = ""
            var accepted=false
            try {
                val w = workspace!!
                if (pending == null) {
                    val latest = api.call("/v3/agent/workspaces/${w.str("id")}") as JSONObject
                    w.put("revision", latest.optInt("revision"))
                }
                val body =
                    pending?.takeIf { it.str("text") == text }
                        ?: json(
                            "text" to text,
                            "subject_refs" to JSONArray(refs),
                            "client_message_id" to UUID.randomUUID().toString(),
                            "expected_revision" to w.optInt("revision"),
                        )
                pending = body
                val r = api.call("/v3/agent/workspaces/${w.str("id")}/runs", body) as JSONObject
                accepted=true
                pending = null
                hydrate()
                val active = workspace!!.items("runs").find { it.str("run_id") == r.str("run_id") }
                if (ended(active?.str("status") ?: r.str("status"))) busy = false
                else listen(r.str("run_id"), active?.optInt("last_seq") ?: 0)
            } catch (e: Exception) {
                busy = false
                progress=""
                if(!accepted) {
                    messages=messages.filterNot {it.str("id")==optimisticId}
                    if(draft.isEmpty()) draft=text
                }
                if (e is ApiException && e.status == 409) {
                    pending = null
                    hydrate()
                }
                throw e
            }
        }
    }

    private fun listen(id: String, after: Int = 0) {
        stream?.cancel()
        runId = id
        busy = true
        val wid = workspace!!.str("id")
        stream =
            viewModelScope.launch {
                var seq = after
                var attempts = 0
                while (isActive) {
                    try {
                        api.events("/v3/agent/workspaces/$wid/runs/$id/events?after=$seq") { event
                            ->
                            withContext(Dispatchers.Main) {
                                seq = event.optInt("seq")
                                val p = event.obj("payload")
                                when (event.str("type")) {
                                    "text_delta" -> {
                                        progress = ""
                                        val mid = p.str("message_id")
                                        liveMessages = liveMessages + mid
                                        val old = messages.find { it.str("id") == mid }
                                        val text =
                                            (old?.items("content")?.joinToString("") {
                                                it.str("text")
                                            } ?: "") + p.str("text")
                                        val m =
                                            json(
                                                "id" to mid,
                                                "role" to "assistant",
                                                "content" to
                                                    JSONArray()
                                                        .put(json("type" to "text", "text" to text)),
                                            )
                                        messages =
                                            if (old == null) messages + m
                                            else messages.map { if (it.str("id") == mid) m else it }
                                    }
                                    "tool.started" -> {
                                        progress = p.str("label")
                                        val latest=messages.lastOrNull {it.str("role")=="assistant" && it.items("content").any {it.str("type")=="text"}}
                                        if(latest!=null && messages.indexOf(latest)>messages.indexOfLast {it.str("role")=="user"}) messages=messages.map {if(it===latest) JSONObject(it.toString()).put("progress_only",true) else it}
                                    }
                                    "resource.notice" -> progress = p.str("message")
                                    "presentation.created" -> {
                                        val ref = p.str("presentation_ref")
                                        loadPresentation(ref)
                                        messages =
                                            messages +
                                                json(
                                                    "id" to ref,
                                                    "role" to "assistant",
                                                    "attachments" to
                                                        json(
                                                            "presentation_refs" to
                                                                JSONArray().put(ref)
                                                        ),
                                                )
                                    }
                                }
                            }
                        }
                        hydrate()
                        val r = workspace!!.items("runs").find { it.str("run_id") == id }
                        if (r == null || ended(r.str("status"))) {
                            busy = false
                            progress = if (r?.str("status") == "FAILED") "本轮未完成" else ""
                            break
                        }
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        if (e is ApiException && e.status in listOf(401, 404, 410)) {
                            busy = false
                            error = e.message ?: "会话已失效"
                            if (e.status == 401) {
                                identity = null
                                clearUser()
                            }
                            break
                        }
                        attempts++
                        progress = "连接中断，正在重连…"
                        if (attempts >= 5) {
                            busy = false
                            error = "连接中断，请重新进入对话恢复"
                            break
                        }
                        delay(1500)
                    }
                }
            }
    }

    fun stop() {
        task {
            api.call(
                "/v3/agent/workspaces/${workspace!!.str("id")}/runs/$runId/cancel",
                json("idempotency_key" to "cancel:$runId"),
            )
            progress = "正在停止…"
        }
    }

    fun focus(presentation: String, objectRef: String) {
        task {
            val w = workspace ?: return@task
            val latest = api.call("/v3/agent/workspaces/${w.str("id")}") as JSONObject
            val result =
                api.call(
                    "/v3/agent/workspaces/${w.str("id")}/focus",
                    json(
                        "presentation_ref" to presentation,
                        "object_ref" to objectRef,
                        "expected_revision" to latest.optInt("revision"),
                    ),
                ) as JSONObject
            workspace?.put("revision", result.optInt("revision"))
        }
    }

    fun feedback(ref: String) {
        task {
            val id = workspace?.str("id") ?: return@task
            api.call(
                "/v3/agent/workspaces/$id/presentations/${ref.removePrefix("artifact:")}/feedback",
                json("event_id" to "rendered:$ref", "status" to "RENDERED"),
            )
        }
    }

    fun earlier() {
        task {
            val w = workspace ?: return@task
            val cursor = w.str("next_cursor")
            if (cursor.isBlank()) return@task
            val p =
                api.call(
                    "/v3/agent/workspaces/${w.str("id")}?cursor=" +
                        URLEncoder.encode(cursor, "UTF-8")
                ) as JSONObject
            val older = p.items("messages").filter { it.str("role") != "tool" }
            messages = older + messages
            workspace?.put("next_cursor", p.opt("next_cursor"))
            for (msg in older) for (ref in
                msg.obj("attachments")
                    .optJSONArray("presentation_refs")
                    .strings()) loadPresentation(ref)
        }
    }

    override fun onCleared() {
        api.eventCall?.cancel()
        super.onCleared()
    }
}
