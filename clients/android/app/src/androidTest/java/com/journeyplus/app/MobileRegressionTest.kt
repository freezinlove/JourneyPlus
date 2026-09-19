package com.journeyplus.app

import android.app.Application
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class MobileRegressionTest {
    @get:Rule val ui=createComposeRule()
    private fun model()=JourneyModel(InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application,false)

    @Test fun completedProgressKeepsArtifactsButNotNarration() {
        val m=model()
        m.messages=listOf(
            JSONObject("""{"id":"u","role":"user","content":[{"type":"text","text":"查询"}]}"""),
            JSONObject("""{"id":"p","role":"assistant","content":[{"type":"text","text":"正在查找"},{"type":"tool_call"}],"attachments":{"presentation_refs":["artifact:fixture"]}}"""),
            JSONObject("""{"id":"f","role":"assistant","content":[{"type":"text","text":"最终结论"}]}"""))
        assertTrue(m.visibleMessages()[1].items("content").isEmpty())
        assertEquals(listOf("artifact:fixture"),m.visibleMessages()[1].obj("attachments").optJSONArray("presentation_refs").strings())
        assertEquals("正在查找",m.messages[1].items("content")[0].str("text"))
        m.messages=m.messages.map {JSONObject(it.toString()).apply {remove("attachments")} }
        ui.setContent {JourneyTheme(false) {ChatScreen(m)}}
        ui.onNodeWithText("正在查找").assertDoesNotExist()
        ui.onAllNodesWithText("JourneyPlus").assertCountEquals(1)
        ui.onNodeWithText("最终结论").assertIsDisplayed()
    }

    @Test fun previousPresentationSurvivesNextTurn() {
        val m=model()
        val ref="artifact:previous"
        m.messages=listOf(
            json("id" to "u1", "role" to "user", "content" to org.json.JSONArray()),
            json("id" to "graph", "role" to "assistant", "attachments" to
                json("presentation_refs" to org.json.JSONArray().put(ref))))
        m.artifacts=mapOf(ref to json("answer" to "历史匹配图", "blocks" to org.json.JSONArray()))
        ui.setContent { JourneyTheme(false) { ChatScreen(m) } }
        ui.onNodeWithText("历史匹配图").assertExists()
        ui.runOnIdle {
            m.messages=m.messages+json("id" to "u2", "role" to "user", "content" to org.json.JSONArray())
            m.busy=true
        }
        ui.onNodeWithText("历史匹配图").assertExists()
        ui.runOnIdle { m.busy=false }
        ui.onNodeWithText("历史匹配图").assertExists()
    }

    @Test fun briefDateHasFullWidthBelowLongFee() {
        val m=model()
        m.detail=JSONObject("""{"program":"KM Rewards","brief":{"title":"KM 测试","summary":"会籍匹配"},"fee":{"label":"已知方案付费，部分费用待确认；存在条件付费项目"},"brief_updated_at":"2026-09-18T16:59:00Z"}""")
        ui.setContent {JourneyTheme(false) {BriefScreen(m)}}
        val fee=ui.onNodeWithText("已知方案付费，部分费用待确认；存在条件付费项目").fetchSemanticsNode().boundsInRoot
        val date=ui.onNodeWithText("2026/9/19").fetchSemanticsNode().boundsInRoot
        assertTrue(date.top>fee.bottom)
        assertTrue("Date must have readable width",date.width>100)
    }

    @Test fun newsTimestampIsDisplayed() {
        val m=model()
        m.news=listOf(JSONObject("""{"ref":"news-test","name":"新闻测试","card":{"summary":"摘要"},"updated_at":"2026-09-18T16:59:00Z"}"""))
        ui.setContent {JourneyTheme(false) {NewsScreen(m)}}
        ui.onNodeWithText("2026/9/19").assertIsDisplayed()
    }
}
