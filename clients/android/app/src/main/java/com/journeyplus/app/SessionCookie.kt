package com.journeyplus.app

import okhttp3.Cookie
import okhttp3.HttpUrl

/** Keep the actual server cookie name; local and cloud deployments use different names. */
internal fun sessionCookie(headers: List<String>, url: HttpUrl): String? =
    headers.mapNotNull { Cookie.parse(url, it) }
        .lastOrNull {
            it.name in setOf("journeyplus_session", "journeyplus_cloud_session") &&
                it.matches(url)
        }
        ?.let {
            if (it.expiresAt <= System.currentTimeMillis()) ""
            else "${it.name}=${it.value}"
        }
