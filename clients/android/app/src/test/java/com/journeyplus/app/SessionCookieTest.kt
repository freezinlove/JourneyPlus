package com.journeyplus.app

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.*
import org.junit.Test

class SessionCookieTest {
    private val url = "https://example.com/auth/login".toHttpUrl()

    @Test fun cloudAndLocalNamesArePreserved() {
        for (name in listOf("journeyplus_session", "journeyplus_cloud_session")) {
            assertEquals("$name=test", sessionCookie(listOf("$name=test; Path=/; HttpOnly; Secure"), url))
        }
    }

    @Test fun unrelatedCookiesAndForeignDomainsAreIgnored() {
        assertNull(sessionCookie(listOf("tracking=value; Path=/"), url))
        assertNull(sessionCookie(listOf("journeyplus_cloud_session=test; Domain=other.com; Path=/"), url))
    }

    @Test fun expiredSessionClearsStoredValue() {
        assertEquals("", sessionCookie(listOf("journeyplus_cloud_session=; Max-Age=0; Path=/"), url))
    }

    @Test fun secureSessionIsNotAcceptedOverHttp() {
        assertNull(sessionCookie(listOf("journeyplus_cloud_session=test; Secure; Path=/"), "http://example.com/auth/login".toHttpUrl()))
    }
}
