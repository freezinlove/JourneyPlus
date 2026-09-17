package com.journeyplus.app

import android.app.Application
import androidx.compose.material3.Text
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Isolated UI fixtures: never sent to the backend or used by the production app. */
class ParityTest {
    @get:Rule val ui = createComposeRule()
    private fun model() = JourneyModel(InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application, false)

    @Test fun newConversationUsesCenteredComposerAndNativeEditableText() {
        val m=model(); m.workspace=JSONObject("{\"id\":\"test\"}")
        ui.setContent { JourneyTheme(false) {ChatScreen(m)} }
        ui.onNodeWithText("想用你的会籍，开启怎样的下一程？").assertIsDisplayed()
        ui.onNodeWithContentDescription("停止回答").assertDoesNotExist()
        ui.onNode(hasSetTextAction()).performTextInput("这是一条用于验证输入框自动换行的长消息。".repeat(6))
        ui.runOnIdle {assertTrue(m.draft.length>100)}
        ui.onNodeWithContentDescription("发送").assertIsDisplayed()
    }
    @Test fun tablesStartCollapsedAndCanBeOpenedAndClosed() {
        ui.setContent {JourneyTheme(false) {CollapsibleTable("会籍匹配表","one") {Text("matrix content")} } }
        ui.onNodeWithText("matrix content").assertDoesNotExist()
        ui.onNodeWithText("会籍匹配表").performClick()
        ui.onNodeWithText("matrix content").assertIsDisplayed()
        ui.onNodeWithText("会籍匹配表").performClick()
        ui.onNodeWithText("matrix content").assertDoesNotExist()
    }
    @Test fun processingShowsStatusButDoesNotCreateEmptyAssistantHeaders() {
        val m=model();m.busy=true;m.progress="正在读取活动资料…"
        m.messages=listOf(JSONObject("{\"id\":\"empty\",\"role\":\"assistant\",\"content\":[]}"))
        ui.setContent {JourneyTheme(false) {ChatScreen(m)} }
        ui.onNodeWithText("正在读取活动资料…").assertIsDisplayed()
        ui.onNodeWithText("JourneyPlus").assertDoesNotExist()
        ui.onNodeWithContentDescription("停止回答").assertIsDisplayed()
    }
    @Test fun feeUnknownIsNeverPresentedAsFree() {
        assertEquals("费用待核实",feeLabel(JSONObject()))
        assertEquals("费用待核实",feeLabel(JSONObject("{\"paid\":null}")))
        assertEquals("免费申请",feeLabel(JSONObject("{\"paid\":false}")))
        assertEquals("付费申请",feeLabel(JSONObject("{\"paid\":true}")))
    }
    @Test fun graphSwipeKeepsHintFixedAndAllowsPageVerticalScroll() {
        val route=JSONObject("""{"data":{"step_refs":["s"],"steps":{"s":{"ref":"s","from_tier_id":"a","to_tier_id":"b","from":"Aster Club Gold","to":"Meridian Club Platinum","paid":false}}}}""")
        ui.setContent {JourneyTheme(false) {
            androidx.compose.foundation.lazy.LazyColumn {
                item {RouteGraph(listOf(route)) {}}
                item {Text("下面的内容\n".repeat(70))}
            }
        }}
        val hint=ui.onNodeWithText("↔  左右滑动查看路径")
        val x=hint.fetchSemanticsNode().boundsInRoot.left
        ui.onNodeWithContentDescription("会籍匹配图").performTouchInput {swipeLeft()}
        assertEquals(x,hint.fetchSemanticsNode().boundsInRoot.left)
        val before=ui.onNodeWithText("下面的内容\n".repeat(70)).fetchSemanticsNode().boundsInRoot.top
        ui.onNodeWithContentDescription("会籍匹配图").performTouchInput {swipeUp()}
        val after=ui.onNodeWithText("下面的内容\n".repeat(70)).fetchSemanticsNode().boundsInRoot.top
        assertTrue("Vertical swipes on graph should scroll the page",after<before)
    }

    @Test fun presentationWaitsUntilPrecedingTextHasBeenDisplayed() {
        val m=model();val text="流式回复".repeat(500)
        m.liveMessages=setOf("reply")
        m.messages=listOf(JSONObject().put("id","reply").put("role","assistant")
            .put("content",org.json.JSONArray().put(JSONObject().put("type","text").put("text",text)))
            .put("attachments",JSONObject().put("presentation_refs",org.json.JSONArray().put("test-presentation"))))
        m.artifacts=mapOf("test-presentation" to JSONObject("""{"blocks":[{"title":"匹配结果测试","type":"summary","payload":{"objects":[]}}]}"""))
        ui.setContent {JourneyTheme(false) {ChatScreen(m)}}
        ui.onNodeWithText("匹配结果测试").assertDoesNotExist()
        ui.runOnIdle {m.displayedLengths["reply"]=text.length}
        ui.onNodeWithText("匹配结果测试").assertExists()
    }

}
