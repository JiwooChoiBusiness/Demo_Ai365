// 모델이 쓸 수 있는 컴포넌트 라이브러리와 그것을 설명하는 프롬프트 옵션. `npm run gen:prompt` 가 두 export 를 읽어
// app/prompts/openui_system_prompt.txt 를 만든다(scripts/gen-prompt.mjs).
// The component library the model may use, and the prompt options it is described with. `npm run gen:prompt`
// reads both exports and writes app/prompts/openui_system_prompt.txt (scripts/gen-prompt.mjs).
//
// 바탕 = OpenUI 채팅 라이브러리(openuiChatLibrary) + 예제 맞춤 컴포넌트. 사진 · 지도는 쓰지 않는다:
// Image · ImageBlock · ImageGallery · 카드 블록류 · PhotoMosaic · Map 을 빼고, 사진 주소를 받던 속성(ListItem.image ·
// OptionCard 의 Image · PlaceCard/ItineraryStop 의 사진)도 없앴다. 프롬프트를 줄이려고 쓰지 않을 기본 컴포넌트
// (EditableTable · Scatter · Radar · Radial · SingleStackedBar · Carousel)도 뺀다.
// Base = OpenUI's chat library (openuiChatLibrary) plus the example's own components. No photos and no maps:
// Image, ImageBlock, ImageGallery, the card blocks, PhotoMosaic and Map are gone, and so are the props that took a
// photo URL (ListItem.image, OptionCard's Image, the photos of PlaceCard and ItineraryStop). Built-ins we will not
// use (EditableTable, Scatter, Radar, Radial, SingleStackedBar, Carousel) are dropped to keep the prompt short.
//
// 방법: openuiChatLibrary.extend({ components: { add, override, remove } }) 로 부모 유니온까지 다시 쓴 뒤, 그
// 컴포넌트들로 createLibrary 를 새로 만든다(그룹 · 메모를 우리 것으로 바꾸려고; extend 는 그룹을 못 바꾼다).
// How: openuiChatLibrary.extend({ components: { add, override, remove } }) rewrites every parent union, then
// createLibrary builds a fresh library from those components (for our own groups and notes, which extend cannot
// change).
//
// 인라인 모드는 끈다: 모든 답이 프로그램 하나(root = Card(...)), 글은 TextContent 안에.
// Inline mode is off: every answer is one program, root = Card(...), with its text in TextContent.
import { z } from "zod/v4";
import { createLibrary, defineComponent } from "@openuidev/react-lang";
import type { ComponentGroup, PromptOptions } from "@openuidev/react-lang";
import { openuiChatLibrary } from "@openuidev/react-ui/genui-lib";

import { Columns, FunnelChart, FunnelStage, Panel, ProgressBar, Stat, StatStrip } from "./components/Dashboard";
import { ItineraryDay, ItineraryStop } from "./components/Itinerary";
import { MermaidDiagram } from "./components/MermaidDiagram";
import { PlaceCard, PlaceList } from "./components/Places";
import { ButtonGrid, Readout, ToolField } from "./components/Tools";
import { functions } from "./functions";

const base = openuiChatLibrary.components;

// 우리 블록 컴포넌트가 들어갈 자식 목록 / The child lists a block-level component of ours may appear in.
const BLOCK_SLOTS = ["Card.children", "SectionItem.content", "TabItem.content", "AccordionItem.content"];

/** 빼는 기본 컴포넌트 / The built-ins we drop. */
export const REMOVED = [
  // 사진 / photos
  "Image",
  "ImageBlock",
  "ImageGallery",
  // 쓰지 않는 표 · 차트 · 배치 / tables, charts and layouts we do not use
  "EditableTable",
  "ScatterChart",
  "ScatterSeries",
  "Point",
  "RadarChart",
  "RadialChart",
  "SingleStackedBarChart",
  "Carousel",
  // 카드 블록(사진 배경 · 사진 카드 포함)과 그 안에서만 쓰는 조각 / the card blocks (with photo cards) and their parts
  "SnippetCardBlock",
  "SnippetCardItem",
  "OverviewCardBlock",
  "OverviewCardItem",
  "ContextCardBlock",
  "ContextCardItem",
  "CompositeCardBlock",
  "CompositeCardItem",
  "VisualCardBlock",
  "VisualCardItem",
  "Text",
  "BoldText",
  "IconText",
  "ImageText",
  "ImageTextLarge",
  "MetricIndicatorInline",
  "MetricIndicatorWithStrikethrough",
];

// 사진 속성을 뺀 ListItem(인자: title, subtitle, actionLabel, action) / ListItem without its photo prop
const ListItem = defineComponent({
  name: "ListItem",
  props: base.ListItem.props.omit({ image: true }),
  description:
    "Item in a ListBlock: a title with an optional subtitle. When action is provided, the item becomes clickable.",
  component: base.ListItem.component,
});

// 번호 목록만 / numbered lists only
const ListBlock = defineComponent({
  name: "ListBlock",
  props: base.ListBlock.props.extend({
    items: z.array(ListItem.ref),
    variant: z.enum(["number"]).optional(),
  }),
  description: "A numbered list of items. Each item can optionally have an action. size small renders a compact list.",
  component: base.ListBlock.component,
});

// 위쪽 내용은 Icon 만 / only an Icon on top
const OptionCard = defineComponent({
  name: "OptionCard",
  props: base.OptionCard.props.extend({ topContent: z.optional(base.Icon.ref) }),
  description:
    "A single selectable card inside an OptionCards group, with a value, title, optional subtitle and an optional Icon on top.",
  component: base.OptionCard.component,
});

const OptionCards = defineComponent({
  name: "OptionCards",
  props: base.OptionCards.props.extend({ items: z.array(OptionCard.ref).default([]) }),
  description:
    "A form field of selectable cards (title, optional subtitle, optional icon) laid out in a responsive grid for choosing one or many options; the selection is stored under `name`.",
  component: base.OptionCards.component,
});

const extended = openuiChatLibrary.extend({
  components: {
    remove: REMOVED,
    override: [ListItem, ListBlock, OptionCard, OptionCards],
    add: [
      { component: MermaidDiagram, slots: BLOCK_SLOTS },
      { component: PlaceList, slots: BLOCK_SLOTS },
      PlaceCard,
      { component: ItineraryDay, slots: BLOCK_SLOTS },
      ItineraryStop,
      { component: StatStrip, slots: BLOCK_SLOTS },
      Stat,
      { component: Columns, slots: BLOCK_SLOTS },
      Panel,
      { component: FunnelChart, slots: BLOCK_SLOTS },
      FunnelStage,
      ProgressBar,
      { component: Readout, slots: BLOCK_SLOTS },
      { component: ButtonGrid, slots: BLOCK_SLOTS },
      { component: ToolField, slots: BLOCK_SLOTS },
    ],
  },
  // @Calc, @ToNumber, @Clamp, @FormatNumber, @Substring, @Length: 화면 도구에 필요한 함수 / what a page tool needs
  functions: { add: functions },
});

// 프롬프트의 컴포넌트 묶음과 메모(OpenUI 메모에서 뺀 컴포넌트 · 사진 이야기를 지우고 우리 것을 더했다).
// The prompt's component groups and notes (OpenUI's notes without the dropped components and photos, plus ours).
const GROUPS: ComponentGroup[] = [
  {
    name: "Content",
    components: [
      "CardHeader",
      "TextContent",
      "MarkDownRenderer",
      "Callout",
      "TextCallout",
      "CodeBlock",
      "Separator",
      "InlineHeader",
      "MermaidDiagram",
    ],
    notes: [
      "- InlineHeader is a compact heading + description pair for labelling a block inside the response (lighter than CardHeader).",
      "- Pass sources on Card ([{ title, sourceName, url }]) when the answer relies on references, and cite them inline in TextContent as [1], [2] (1-based index into sources). A Sources strip renders at the bottom of the card.",
    ],
  },
  { name: "Tables", components: ["Table", "Col"] },
  { name: "Charts (2D)", components: ["BarChart", "LineChart", "AreaChart", "HorizontalBarChart", "Series"] },
  { name: "Charts (1D)", components: ["PieChart", "Slice"] },
  {
    name: "Dashboard",
    components: ["StatStrip", "Stat", "Columns", "Panel", "FunnelChart", "FunnelStage", "ProgressBar"],
    notes: ["- Stat, Panel and FunnelStage appear only inside StatStrip, Columns and FunnelChart; ProgressBar goes in a Table Col's data."],
  },
  {
    name: "Forms",
    components: [
      "Form",
      "FormControl",
      "Label",
      "Input",
      "TextArea",
      "Select",
      "SelectItem",
      "DatePicker",
      "Slider",
      "CheckBoxGroup",
      "CheckBoxItem",
      "RadioGroup",
      "RadioItem",
      "SwitchGroup",
      "SwitchItem",
      "Chips",
      "ChipItem",
      "OptionCards",
      "OptionCard",
    ],
    notes: [
      "- Chips: compact single/multiple selection pills. Use ChipItem references for each option.",
      "- OptionCards: larger selectable cards with title, subtitle and an optional Icon on top. Use OptionCard references for each option.",
      "- Define EACH FormControl as its own reference; do NOT inline all controls in one array.",
      "- NEVER nest Form inside Form.",
      "- Form requires explicit buttons. Always pass a Buttons(...) reference as the second Form argument: Form(name, buttons, fields).",
      "- rules is an optional object: { required: true, email: true, min: 8, maxLength: 100 }",
      "- The renderer shows error messages automatically; do NOT generate error text in the UI",
    ],
  },
  {
    name: "Buttons",
    components: ["Button", "Buttons", "Icon", "IconButton"],
    notes: ["- Icon renders a lucide icon by kebab-case name; it is also the icon of IconButton, Tag, ChipItem and OptionCard."],
  },
  {
    name: "Lists & Follow-ups",
    components: ["ListBlock", "ListItem", "FollowUpBlock", "FollowUpItem"],
    notes: [
      "- Use ListBlock with ListItem references for numbered lists.",
      "- Use FollowUpBlock with FollowUpItem references at the end of a response to suggest next actions.",
      "- A ListItem is clickable ONLY when given an action (4th argument); without one it is plain text.",
      "- Clicking a FollowUpItem, or a ListItem with a @ToAssistant action, sends text to the LLM as a user message.",
      '- Example: list = ListBlock([item1, item2])  item1 = ListItem("Option A", "Details about A", null, @ToAssistant("Option A"))',
    ],
  },
  {
    name: "Sections",
    components: ["SectionBlock", "SectionItem"],
    notes: [
      "- SectionBlock renders collapsible accordion sections that auto-open as they stream.",
      "- Each section needs a unique `value` id, a `trigger` label, and a `content` array.",
      '- Example: sections = SectionBlock([s1, s2])  s1 = SectionItem("intro", "Introduction", [content1])',
      "- Set isFoldable=false to render sections as flat headers instead of accordion.",
    ],
  },
  {
    name: "Layout",
    components: ["Tabs", "TabItem", "Accordion", "AccordionItem", "Steps", "StepsItem"],
    notes: ["- Use Tabs to present alternative views: each TabItem has a value id, trigger label, and content array."],
  },
  {
    name: "Data Display",
    components: ["TagBlock", "Tag", "EntityList"],
    notes: [
      "- EntityList is a compact two-column list of { left, right } rows (e.g. name / value). size='default' also supports a header and footer row; size='small' does not.",
    ],
  },
  {
    name: "Places & schedules",
    components: ["PlaceList", "PlaceCard", "ItineraryDay", "ItineraryStop"],
    notes: ["- PlaceCard appears only inside PlaceList, ItineraryStop only inside ItineraryDay. Neither has a photo."],
  },
  {
    name: "Tools that work in the page",
    components: ["Readout", "ButtonGrid", "ToolField"],
  },
];

export const library = createLibrary({
  root: "Card",
  components: Object.values(extended.components),
  componentGroups: GROUPS,
  functions: Object.values(extended.functions ?? {}),
});

// 예시(배치는 규칙보다 예시가 훨씬 크게 이끈다). 사진 주소 없음. 한국어 예시 셋(사내 문서 · 비교표 · 짧은 답)은
// 계약 8절: 출처 src1 · src2 는 시스템이 먼저 정의하고 모델은 [src1, src2] 로만 가리킨다.
// Examples (they steer the layout far more than rules do). No photo URLs. The three Korean ones (internal
// documents, a comparison table, a short answer) follow contract section 8: the system defines src1 and src2
// first, and the model only refers to them as [src1, src2].
const EXAMPLES = [
  `Example 1: 사내 문서 답 (출처 src1, src2 는 시스템이 이미 정의했다. 예: src1 = {title: "여비규정.pdf p.3", sourceName: "인사 › 규정", url: "ai365://kn/%EC%97%AC%EB%B9%84%EA%B7%9C%EC%A0%95.pdf?page=3"}. 다시 정의하지 말고 루트 Card 두 번째 인자에 [src1, src2] 로만 쓴다. [1] 은 src1, [2] 는 src2. 숫자는 예시):

root = Card([header, summary, steps, limits, note, followUps], [src1, src2])
header = CardHeader("국내 출장비 정산 절차", "인사 › 규정 기준")
summary = TextContent("국내 출장비는 출장을 마친 날부터 **7일 안에** 정산합니다 [1]. 숙박비는 직급별 한도 안에서 실비로 지급합니다 [2].")
steps = Steps([st1, st2, st3])
st1 = StepsItem("증빙 모으기", "영수증과 카드 전표를 모읍니다.")
st2 = StepsItem("정산서 작성", "전자결재에서 출장비 정산서를 올립니다.")
st3 = StepsItem("승인과 지급", "팀장이 승인하면 다음 급여일에 지급됩니다.")
limits = EntityList([{left: "숙박비(사원 · 대리)", right: "1박 8만 원"}, {left: "식비", right: "1일 3만 원"}])
note = Callout("info", "확인하세요", "법인카드로 낸 비용은 개인 정산에서 뺍니다.")
followUps = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("해외 출장비 규정도 알려줘")
fu2 = FollowUpItem("정산서 양식은 어디 있어?")`,

  `Example 2: Dashboard or data overview (headline numbers first, then charts side by side, then a table; the figures here are made up for the example):

root = Card([header, stats, charts, tableTitle, table, followUps])
header = CardHeader("Performance Overview", "All regions, 2025 year to date")
stats = StatStrip([s1, s2, s3])
s1 = Stat("$110.4M", "Total ad spend", "+8.2%", "bad")
s2 = Stat("$425.5M", "Total sales", "+14.1%")
s3 = Stat("12", "Active campaigns")
charts = Columns([trendPanel, funnelPanel])
trendPanel = Panel("Sales by quarter", [trend], "In $M", true)
trend = BarChart(["Q1", "Q2", "Q3", "Q4"], [sNA, sEU], "grouped")
sNA = Series("North America", [62, 71, 80, 86])
sEU = Series("Europe", [35, 40, 46, 51])
funnelPanel = Panel("Campaign funnel", [funnel])
funnel = FunnelChart([f1, f2, f3])
f1 = FunnelStage("Clicks", 310000, "310K")
f2 = FunnelStage("Sign-ups", 42000, "42K")
f3 = FunnelStage("Purchases", 9800, "9.8K")
tableTitle = InlineHeader("Regional campaigns", "Sales against the best region")
table = Table([Col("Campaign", ["NA-01", "EU-02"]), Col("Sales", [ProgressBar(299, 299, "$299.0M"), ProgressBar(172.4, 299, "$172.4M")]), Col("ROI", [Tag("523%", null, "sm", "success"), Tag("272%", null, "sm", "warning")])])
followUps = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("Break sales down by month")
fu2 = FollowUpItem("Which campaign should get more budget?")`,

  `Example 3: 비교표 답 (둘 이상을 견주면 Table, 숫자는 예시):

root = Card([header, intro, table, note, followUps], [src1])
header = CardHeader("휴가 종류 비교", "연차 · 반차 · 병가")
intro = TextContent("세 휴가는 **신청 기한**과 **증빙**이 다릅니다 [1].")
table = Table([Col("항목", ["신청 기한", "증빙", "급여"]), Col("연차", ["3일 전", "없음", "유급"]), Col("반차", ["전날", "없음", "유급"]), Col("병가", ["당일", "진단서(3일 이상)", "유급(연 5일)"])])
note = TextContent("반차는 연차 0.5일로 셉니다.", "small")
followUps = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("남은 연차는 어떻게 확인해?")
fu2 = FollowUpItem("병가 신청 절차도 알려줘")`,

  `Example 4: 짧은 답 (인사나 간단한 질문은 짧게):

root = Card([answer, followUps])
answer = TextContent("회의실은 그룹웨어 **일정 › 회의실** 메뉴에서 날짜와 시간을 고르면 바로 예약됩니다.")
followUps = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("이번 주 비어 있는 회의실 보여 줘")
fu2 = FollowUpItem("예약을 취소하려면?")`,

  `Example 5: Form (help-me-choose or plan asks: a short intro, then a compact form):

root = Card([header, intro, form])
header = CardHeader("Plan Your Trip", "Tell me your preferences")
intro = TextContent("Fill in the quick form below for a tailored plan.")
form = Form("trip-planner", formButtons, [fcDestination, fcDates, fcTravellers, fcTripType, fcBudget, fcNotes])
formButtons = Buttons([btnSubmit, btnSkip], "row")
btnSubmit = Button("Plan My Trip", @ToAssistant("Help me plan a trip based on my form submission"), "primary")
btnSkip = Button("Just Surprise Me", @ToAssistant("Skip the form and surprise me with a destination and itinerary"), "secondary")
fcDestination = FormControl("Destination", destinationInput, "Leave blank if you'd like suggestions")
destinationInput = Input("destination", "e.g. Tokyo, Japan", "text")
fcDates = FormControl("Travel Dates", datesPicker, "Select your start and end dates")
datesPicker = DatePicker("travel-dates", "range", { required: true })
fcTravellers = FormControl("Number of Travellers", travellersSelect)
travellersSelect = Select("num-travellers", [tr1, tr2, tr3], "Select number of travellers", { required: true })
tr1 = SelectItem("1", "Solo")
tr2 = SelectItem("2", "Couple")
tr3 = SelectItem("3+", "3 or more")
fcTripType = FormControl("Trip Type", tripTypeCards)
tripTypeCards = OptionCards("trip-type", "single", [oc1, oc2], { required: true })
oc1 = OptionCard("city", "City Break", "Museums and food", oc1icon)
oc1icon = Icon("building-2", "buildings")
oc2 = OptionCard("nature", "Nature", "Hiking and views", oc2icon)
oc2icon = Icon("mountain", "nature")
fcBudget = FormControl("Budget per person (USD)", budgetSlider)
budgetSlider = Slider("budget", "discrete", 500, 10000, 500, [2500], "Budget (USD)")
fcNotes = FormControl("Special Requests", notesArea)
notesArea = TextArea("special-requests", "e.g. vegetarian meals, wheelchair access", 3)`,

  `Example 6: A list of places (restaurants, hotels, offices or attractions to choose from; no photos):

root = Card([header, intro, places, followUps], [src1])
header = CardHeader("Where to Eat near Gangnam Station", "Local favourites for a team lunch")
intro = TextContent("Gangnam has many Korean set-menu places that take groups [1].")
places = PlaceList([p1, p2])
p1 = PlaceCard("Hanilkwan", "Classic **bulgogi** set menus and private rooms [1].", "Good for groups", "success", [{label: "Area", value: "Gangnam"}])
p2 = PlaceCard("Mingles", "Modern Korean tasting menu; book ahead [1].", "Special occasions", "info", [{label: "Area", value: "Cheongdam"}])
followUps = FollowUpBlock([fu1])
fu1 = FollowUpItem("Only places within a 5-minute walk")`,

  `Example 7: A trip or schedule (one ItineraryDay per day with its timed stops; no photos):

root = Card([header, intro, day1, day2, followUps], [src1])
header = CardHeader("2 Days in Busan", "Beaches, markets and the harbour")
intro = TextContent("Busan is easy by subway; start early to beat the crowds [1].")
day1 = ItineraryDay("Day 1: Haeundae", [d1s1, d1s2], "Beach and coastal walk")
d1s1 = ItineraryStop("Haeundae Beach", "9:00 AM", "A long sandy beach with a boardwalk [1].")
d1s2 = ItineraryStop("Dongbaekseom", "11:00 AM", "A short island trail with sea views [1].")
day2 = ItineraryDay("Day 2: Old town", [d2s1, d2s2], "Markets and the port")
d2s1 = ItineraryStop("Jagalchi Market", "10:00 AM", "Korea's largest seafood market [1].")
d2s2 = ItineraryStop("Gamcheon Culture Village", "2:00 PM", "Hillside lanes of painted houses [1].")
followUps = FollowUpBlock([fu1])
fu1 = FollowUpItem("Add a day trip to Gyeongju")`,

  `Example 8: A working tool with keys (a calculator: every key changes $display with @Set; = works it out with @Calc):

root = Card([header, screen, keys])
header = CardHeader("Calculator", "Everyday sums, worked out right here")
$display = "0"
screen = Readout($display, "Calculator")
keys = ButtonGrid([kAc, kBack, kDiv, kMul, k7, k8, k9, kSub, k4, k5, k6, kAdd, k1, k2, k3, kEq, k0, kDot], 4)
kAc = Button("AC", @Reset($display), "secondary")
kBack = Button("⌫", @Set($display, @Length($display) > 1 ? @Substring($display, 0, -1) : "0"), "secondary")
kDiv = Button("÷", @Set($display, $display + "÷"), "secondary")
kMul = Button("×", @Set($display, $display + "×"), "secondary")
kSub = Button("−", @Set($display, $display + "−"), "secondary")
kAdd = Button("+", @Set($display, $display + "+"), "secondary")
k7 = Button("7", @Set($display, $display == "0" ? "7" : $display + "7"), "tertiary")
k8 = Button("8", @Set($display, $display == "0" ? "8" : $display + "8"), "tertiary")
k9 = Button("9", @Set($display, $display == "0" ? "9" : $display + "9"), "tertiary")
k4 = Button("4", @Set($display, $display == "0" ? "4" : $display + "4"), "tertiary")
k5 = Button("5", @Set($display, $display == "0" ? "5" : $display + "5"), "tertiary")
k6 = Button("6", @Set($display, $display == "0" ? "6" : $display + "6"), "tertiary")
k1 = Button("1", @Set($display, $display == "0" ? "1" : $display + "1"), "tertiary")
k2 = Button("2", @Set($display, $display == "0" ? "2" : $display + "2"), "tertiary")
k3 = Button("3", @Set($display, $display == "0" ? "3" : $display + "3"), "tertiary")
k0 = Button("0", @Set($display, $display == "0" ? "0" : $display + "0"), "tertiary")
kDot = Button(".", @Set($display, $display + "."), "tertiary")
kEq = Button("=", @Set($display, "" + @Calc($display, "Error")), "primary")`,

  `Example 9: A live calculator from inputs (the results and the formula update as the user types; no submit button; the defaults are editable assumptions):

root = Card([header, results, formula, fPeople, fMinutes, fWage, reset])
header = CardHeader("Meeting Cost Calculator", "Change any value; the cost updates as you type")
$people = "8"
$minutes = "60"
$wage = "50"
people = @Clamp(@ToNumber($people), 0, 1000)
minutes = @Clamp(@ToNumber($minutes), 0, 600)
wage = @Clamp(@ToNumber($wage), 0, 100000)
cost = people * minutes / 60 * wage
results = StatStrip([sMeeting, sYear])
sMeeting = Stat("$" + @FormatNumber(cost, 0), "One meeting", null, null, "💸")
sYear = Stat("$" + @FormatNumber(cost * 52, 0), "Weekly for a year", null, null, "📅")
formula = TextContent("**Cost** = people × minutes ÷ 60 × hourly wage = " + people + " × " + minutes + " ÷ 60 × $" + wage + " = **$" + @FormatNumber(cost, 0) + "**")
fPeople = ToolField("People", Input("people", "8", "number", null, $people), "0 to 1,000")
fMinutes = ToolField("Minutes", Input("minutes", "60", "number", null, $minutes), "0 to 600")
fWage = ToolField("Hourly wage ($)", Input("wage", "50", "number", null, $wage), "Never negative")
reset = Buttons([Button("Reset", @Reset($people, $minutes, $wage), "secondary")])`,

  // 계약 9절: 데이터 · 그룹웨어 답. 서버가 d1 · d1top · d1sum · gw1 · src1 을 먼저 정의하고 모델은 참조만 한다(숫자는 코드).
  // Contract section 9: data and groupware answers. The server defines d1, d1top, d1sum, gw1 and src1 first; the model
  // only refers to them (the numbers come from code).
  `Example 10: 데이터 분석 답 (d1 · d1top · d1sum · src1 은 시스템이 이미 정의했다. 예: d1 = [{c1: "1월", c2: 42.5, c3: 96}, ...] (12행, c1=월, c2=매출액(억 원), c3=주문 건수), d1top = d1 의 앞 10행, d1sum = {c2: {sum, avg, min, max, first, last, change, chg}, c3: {...}} (chg 는 부호 붙은 변화율 글자, 예: "+21.6%", 없으면 ""), src1 = {title: "월별 매출", sourceName: "데이터 분석 › 영업 › DB", url: "ai365://data/sales_monthly?ws=sales"}. 다시 정의하지 말고 이름으로만 쓴다. 차트 · Stat 의 숫자는 이 문장에서 가져오고 글 속 숫자는 @FormatNumber 로 만든다. 숫자를 직접 옮겨 적지 않는다. 전체 표는 답 아래 표 카드에 있으니 Table 을 쓰지 않는다(요약 · StatStrip · 차트로 답한다). 행이 50개를 넘어 d1 이 잘렸으면 합계 · 평균 · 최소 · 최대는 d1sum 에서만 가져온다):

root = Card([header, summary, stats, chart, note, followUps], [src1])
header = CardHeader("월별 매출 추이", "영업 실적 데이터 기준")
summary = TextContent("12개월 매출 합계는 **" + @FormatNumber(d1sum.c2.sum) + "억 원**이고, 첫 달 대비 마지막 달 변화율은 " + @FormatNumber(d1sum.c2.change, 1) + "%입니다 [1].")
stats = StatStrip([s1, s2, s3])
s1 = Stat(@FormatNumber(d1sum.c2.sum) + "억 원", "매출 합계")
s2 = Stat(@FormatNumber(d1sum.c2.avg) + "억 원", "월평균 매출")
s3 = Stat(@FormatNumber(d1sum.c2.last) + "억 원", "마지막 달 매출", d1sum.c2.chg)
chart = LineChart(d1.c1, [Series("매출액", d1.c2)], "natural", null, "억 원")
note = Callout("info", "변동 폭", "월 매출은 최저 " + @FormatNumber(d1sum.c2.min) + "억 원에서 최고 " + @FormatNumber(d1sum.c2.max) + "억 원 사이입니다.")
followUps = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("분기별로 묶어서 보여줘")
fu2 = FollowUpItem("주문 건수가 가장 많은 달은?")`,

  `Example 11: 그룹웨어 목록 답 (gw1 · src1 은 시스템이 이미 정의했다. 예: gw1 = [{left: "3분기 예산안 검토 요청", right: "김지민 · 10:12"}, ...] (안 읽은 메일, left=제목, right=보낸 사람 · 시각), src1 = {title: "받은편지함", sourceName: "그룹웨어 › 메일"}. 다시 정의하지 말고 이름으로만 쓴다. 단추 · 후속 질문은 @ToAssistant 로 다음 요청을 보낼 뿐이고, 발송 · 변경 같은 실행은 하지 않으며 했다고 쓰지도 않는다):

root = Card([header, summary, list, actions, followUps], [src1])
header = CardHeader("안 읽은 메일", "그룹웨어 › 메일")
summary = TextContent("안 읽은 메일이 **" + @Count(gw1) + "통** 있습니다 [1]. 맨 위 메일은 ‘" + gw1[0].left + "’입니다.")
list = EntityList(gw1)
actions = Buttons([b1, b2])
b1 = Button("답장 초안 쓰기", @ToAssistant("‘" + gw1[0].left + "’ 메일에 답장 초안 써줘"), "primary")
b2 = Button("급한 메일 고르기", @ToAssistant("안 읽은 메일 중 급한 것만 골라줘"), "secondary")
followUps = FollowUpBlock([fu1, fu2])
fu1 = FollowUpItem("오늘 일정도 보여줘")
fu2 = FollowUpItem("김지민 님 메일만 모아줘")`,
];

// 규칙(OpenUI 채팅 규칙에서 뺀 컴포넌트 · 사진 이야기를 지우고, 예제 규칙에서 사진 · 지도 · 날씨를 뺀 것).
// Rules (OpenUI's chat rules without the dropped components and photos, plus the example's rules without
// photos, maps and weather).
const RULES = [
  "Every response is a single Card(children); children stack vertically automatically. No layout params are needed on Card.",
  "Card is the only layout container. Do NOT use Stack. Use Tabs to switch between views and Columns to put panels side by side.",
  "Use FollowUpBlock at the END of a Card to suggest what the user can do or ask next.",
  "Use ListBlock when presenting a set of options or steps; give each ListItem an action (4th argument) to make it clickable. Without one the item is plain text.",
  "Use SectionBlock to group long responses into collapsible sections: good for reports, FAQs, and structured content. Each SectionItem needs a unique value id, a trigger (header label), and a content array.",
  "For forms, define one FormControl reference per field so controls can stream progressively, always provide the second Form argument with Buttons(...): Form(name, buttons, fields), and never nest Form inside Form.",
  "CardHeader is the page-level heading: place it as the first child of Card. InlineHeader is a lighter subsection label for a block inside the response, and is redundant when the following component already has a heading.",
  "Never use Callout or TextCallout to justify why you did what you did or for any meta-information.",
  "There are no image components: never write image or photo URLs anywhere.",
  "EntityList: use size \"default\" (it supports header and footer rows).",
  "Tag variant must be semantically correct (success=positive, danger=negative, warning=cautionary, info=informational, neutral=label); Tag takes an optional Icon second, so use Tag(text, icon, size, variant) when a variant is needed. TagBlock takes plain strings; keep it to at most 3 tags.",
  "ListBlock is for ordered sequences and rankings; Steps is for ordered sequential processes only.",
  "Use SectionBlock to divide a long response into independent, equally prominent topics; use Tabs when the items are alternative views of the same thing; set isFoldable=false unless a section has 4+ distinct blocks; never make SectionBlock the first Card child.",
  "Accordion is for supplementary or FAQ content only, never primary information, 3-5 items max, and always the last component in its section or card.",
  "Charts: LineChart/AreaChart variant \"natural\" for smooth trends and \"linear\" for precise point-to-point data; BarChart \"grouped\" for side-by-side comparison and \"stacked\" for part-to-whole; prefer HorizontalBarChart when category labels are long or numerous. For large values, scale the data and put the unit in the axis label (e.g. yLabel \"Revenue ($k)\").",
  "Quantitative asks get a chart (plus a StatStrip where useful) in the FIRST response; do not answer numbers with prose or a table alone.",
  "Table is column-oriented: each Col holds its own data array, and every column's array must have the same length. A cell is a plain string or number, or a ProgressBar or Tag.",
  'A Form is for answers sent to the assistant: every Form MUST have EXACTLY ONE submit Button with variant "primary", which validates the form; other buttons (secondary/tertiary escape hatches like "Just Surprise Me") skip validation, and there is never a reset button. A tool that works in the page (Examples 8 and 9) has no Form.',
  "Prefer structured inputs (Select, Chips, OptionCards, DatePicker, Slider) over free-text Input, give every FormControl a clear label (and a hint where it prevents mistakes), and keep each field name unique within the response.",
  "Validation rules ({ required: true, email: true, minLength: 8, ... }) are enforced with inline errors: use them for genuinely essential fields, but never require a free-text field where leaving it blank is meaningful.",
  "An input works inside a FormControl within a Form, or, bound to a $variable, inside a ToolField of a tool that works in the page. For tappable suggestion choices outside both, use Buttons whose Button actions are @ToAssistant, never a bare OptionCards or Chips.",
  "Only add Buttons for real actions: form submit, @Set or @Reset in a tool that works in the page, @OpenUrl with a URL from a tool or the user (never fabricated), or a @ToAssistant follow-up. Never add a button for an app action (open, download, export, edit) you cannot perform.",
  "Every Button label must accurately describe what clicking it does; use \"primary\" for the main action and \"secondary\"/\"tertiary\" only for lower-emphasis supporting actions.",
  "Icon: always include the category argument; it enables fallback matching when the exact lucide name is unavailable.",
  "Pass sources on Card ONLY when the answer relies on real references you actually have, and cite them inline in TextContent as [1], [2] (1-based index into sources).",
  "Write [n] citations only inside TextContent, Callout and TextCallout descriptions, StepsItem details, ListItem subtitles and the descriptions of PlaceCard and ItineraryStop. Anywhere else they show as plain text.",
  "For a flowchart, process, sequence or any other diagram, use MermaidDiagram with valid Mermaid code. Never put Mermaid code in a CodeBlock.",
  "Choose the layout from the kind of answer, as in Examples 6 and 7: a list of places to choose from is a PlaceList with one PlaceCard per place, not a ListBlock; a trip or multi-day schedule is one ItineraryDay per day with its timed ItineraryStops.",
  "A dashboard, report or overview of numbers follows Example 2: StatStrip with the headline numbers, then Columns with charts in Panels side by side (two, or three small ones, per row), then a Table. Use ProgressBar in a Table column to compare values and Tag for statuses or percentages; FunnelChart for stages that narrow down.",
  "When the system has defined data statements (d1, d1top, d1sum, gw1), follow Examples 10 and 11: refer to them for every number and list, and never copy their values into the program.",
  "Never invent figures. Use only numbers the user gave, the conversation holds or the given sources state, and cite them. When the user asks for dummy, sample or example data, make it up, and say in the CardHeader subtitle that it is sample data. A live tool's input defaults are editable assumptions, not facts.",
  "Anything the page can work out from what the user enters works in the page, as in Examples 8 and 9: calculators, estimators, converters, budgets, scores, counters, checklists. $variables hold the state; inputs in ToolFields are bound to them; keys change them with @Set; results are expressions of them, shown in Readout, Stat or TextContent, and update at once. Read an input's text with @ToNumber, keep it in range with @Clamp, show results with @FormatNumber. Every Button in such a tool has an action (a Button without one sends its label to the assistant). Never a Form, a Calculate button or @ToAssistant to compute what the page can compute; those are for what needs you, such as searching, advice or planning.",
];

export const promptOptions: PromptOptions = {
  // $변수 · @Set · @Reset · 식 · 내장 함수(채팅 기본은 꺼짐) / $variables, @Set and @Reset, expressions and the built-ins
  bindings: true,
  examples: EXAMPLES,
  additionalRules: RULES,
};
