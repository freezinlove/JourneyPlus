package com.journeyplus.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

fun JSONObject.str(key: String, fallback: String = "") =
    if (isNull(key)) fallback else optString(key, fallback)

fun JSONObject.obj(key: String) = optJSONObject(key) ?: JSONObject()

fun JSONObject.items(key: String) = optJSONArray(key).objects()

fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }

fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).map { optString(it) }

fun json(vararg pairs: Pair<String, Any?>) =
    JSONObject().apply { pairs.forEach { (k, v) -> put(k, v ?: JSONObject.NULL) } }

fun ended(status: String) = status in listOf("COMPLETED", "PARTIAL", "CANCELED", "FAILED")

class ApiException(val status: Int, message: String) : Exception(message)

/** Session secrets are encrypted using an app-owned Android Keystore key. */
class SessionVault(context: Context) {
    private val prefs = context.getSharedPreferences("session", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return (store.getKey("journeyplus-session", null) as? SecretKey)
            ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
                .apply {
                    init(
                        KeyGenParameterSpec.Builder(
                                "journeyplus-session",
                                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                            )
                            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                            .build()
                    )
                }
                .generateKey()
    }

    fun write(value: String) {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        prefs
            .edit()
            .putString(
                "cookie",
                Base64.encodeToString(c.iv + c.doFinal(value.toByteArray()), Base64.NO_WRAP),
            )
            .apply()
    }

    fun read(): String =
        runCatching {
                val bytes = Base64.decode(prefs.getString("cookie", ""), Base64.NO_WRAP)
                val c = Cipher.getInstance("AES/GCM/NoPadding")
                c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
                String(c.doFinal(bytes.copyOfRange(12, bytes.size)))
            }
            .getOrDefault("")

    fun clear() {
        prefs.edit().clear().apply()
    }
}

class Api(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val vault = SessionVault(context)
    var base: String = prefs.getString("server", "http://10.0.2.2:8000")!!
        private set

    private var cookie = vault.read()
    private val client =
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(45, TimeUnit.SECONDS)
            .build()
    @Volatile var eventCall: Call? = null

    fun configure(url: String) {
        val normalized = url.trim().trimEnd('/')
        require(
            normalized.startsWith("https://") ||
                BuildConfig.DEBUG && normalized.startsWith("http://")
        ) {
            "请输入 HTTPS 服务地址"
        }
        if (base != normalized) clear()
        base = normalized
        prefs.edit().putString("server", base).apply()
    }

    fun clear() {
        eventCall?.cancel()
        cookie = ""
        vault.clear()
    }

    private fun request(path: String, body: JSONObject? = null, method: String = "GET") =
        Request.Builder()
            .url(base + path)
            .apply {
                if (cookie.isNotEmpty()) header("Cookie", cookie)
                method(
                    method,
                    if (method in listOf("POST", "PATCH", "PUT"))
                        (body ?: JSONObject())
                            .toString()
                            .toRequestBody("application/json".toMediaType())
                    else null,
                )
            }
            .build()

    suspend fun call(
        path: String,
        body: JSONObject? = null,
        method: String = if (body == null) "GET" else "POST",
    ): Any =
        withContext(Dispatchers.IO) {
            client.newCall(request(path, body, method)).execute().use { r ->
                val raw = r.body?.string().orEmpty()
                if (!r.isSuccessful) {
                    if (r.code == 401) clear()
                    throw ApiException(
                        r.code,
                        if (r.code == 401) "请重新登录"
                        else
                            runCatching {
                                    JSONObject(raw)
                                        .str(
                                            "message",
                                            JSONObject(raw).str("detail", "请求未完成（${r.code}）"),
                                        )
                                }
                                .getOrDefault("请求未完成（${r.code}）"),
                    )
                }
                r.headers("Set-Cookie")
                    .firstOrNull { it.startsWith("journeyplus_session=") }
                    ?.let {
                        cookie = it.substringBefore(';')
                        vault.write(cookie)
                    }
                if (raw.startsWith("[")) JSONArray(raw)
                else if (raw.isBlank()) JSONObject() else JSONObject(raw)
            }
        }

    suspend fun events(path: String, onEvent: suspend (JSONObject) -> Unit) =
        withContext(Dispatchers.IO) {
            val c = client.newCall(request(path))
            eventCall = c
            try {
                c.execute().use { r ->
                    if (!r.isSuccessful) throw ApiException(r.code, "对话连接失败（${r.code}）")
                    val source = r.body!!.source()
                    val data = StringBuilder()
                    while (!source.exhausted()) {
                        val line = source.readUtf8Line() ?: break
                        if (line.startsWith("data:"))
                            data.append(line.removePrefix("data:").trimStart())
                        if (line.isEmpty() && data.isNotEmpty()) {
                            onEvent(JSONObject(data.toString()))
                            data.clear()
                        }
                    }
                }
            } finally {
                if (eventCall === c) eventCall = null
            }
        }
}
