/* 채팅 실시간 위젯(2026-10-06) — 날씨 · 환율 · 지도(장소) 카드. 서버(app/live_widgets.py)가 done.cards(라이브)와
   meta.cards(복원)에 kind 'weather' | 'fx' | 'places' 카드를 싣고, adapter.js 가 답변 본문(.ai-body) 바로 뒤에
   ai365WgInsert(body, cards) 로 넣는다(복사 버튼에 카드 글이 섞이지 않게). 숫자는 서버가 받은 API 값 그대로다.
   - 날씨: 7일 카드 · °C/°F · 시간별 온도 꺾은선/강수 확률 막대(직접 그린 SVG, 시각은 KST).
   - 환율: 두 통화 행 + 출처 · 기준 시각.
   - 지도: 구글 지도(Maps JavaScript, 지도 1개마다 /api/live/map-load 로 월 한도 확인) + 별점 핀 + 장소 카드,
     [크게 보기] = 사이드바를 남긴 채 .main 을 덮는 층(목록 · 핀 팝업 · 가게 정보). 구글 약관상 장소 데이터는 저장하지 않아
     복원본은 [지도 다시 불러오기] 자리표시다. 사진 · 가게 정보는 보이거나 열 때만 부른다(무료 범위).
   Chat live widgets (2026-10-06) — weather, exchange-rate and map (place) cards. The server (app/live_widgets.py) puts
   kind 'weather' | 'fx' | 'places' cards in done.cards (live) and meta.cards (restore); adapter.js inserts them right
   after the answer body via ai365WgInsert(body, cards) so the copy button never picks up card text. Numbers are the
   API values as received. Weather: 7 day cards, °C/°F, hourly temperature line / precipitation-chance bars (hand-drawn
   SVG, KST times). FX: two currency rows plus source and as-of time. Map: Google Maps (each map checks the monthly
   limit via /api/live/map-load) with rating pins and place cards; [Expand] = a layer over .main that keeps the
   sidebar (list, pin popup, place details). Google's terms forbid storing place data, so a restored card is a
   [Reload map] placeholder. Photos and details load only when visible or opened (free tier). */

var AI365_WG = { photo: {}, detail: {}, maps: null, authFailed: false, mapx: null };

(function () {
  if (document.getElementById('ai365WgCss')) return;
  // Figma DS 적용(2026-10-28, docs/figma-design-system-spec.md 6 · 7절, 사용자 지시 "모두 디자인 시스템대로"): 위젯 카드 = 제품 시트 답변 카드
  // (r16 · 옅은 1px Stroke 2), 버튼 = DS 코어 직사각 r8(Secondary · Primary, hover · pressed · disabled 단계), 그래프 종류 = DS Dropdown(Outline 트리거 +
  // 목록 r8 · Shadow 16), 떠 있는 패널 · 팝업 = Shadow 16, 지도 조작 = DS 아이콘 버튼 L, 글자 = DS 글자 단계(500 → 400, 800 → 700).
  // 날씨 아이콘 · 시간별 그래프 · 지도 바탕 · 핀 같은 데이터 색은 그대로. 이 파일은 토큰 없는 단독 페이지(테스트)에서도 돌므로 모든 DS 토큰에
  // adapter.js ai365DsTokens 와 같은 값을 기본값으로 함께 적는다.
  // Figma DS applied (2026-10-28, sections 6 and 7 of docs/figma-design-system-spec.md; the user's "apply the design system everywhere"):
  // widget cards follow the product sheet's answer card (r16, a light 1px Stroke 2), buttons are DS core r8 rectangles (Secondary and
  // Primary with hover, pressed and disabled steps), the graph switch is a DS Dropdown (Outline trigger, r8 list with Shadow 16), floating
  // panels and popups use Shadow 16, map controls are DS icon buttons L, and text follows the DS type ramp (500 → 400, 800 → 700). Data
  // colours (weather icons, the hourly graph, the map backdrop and pins) stay. This file also runs on token-less standalone pages
  // (tests), so every DS token carries the adapter.js ai365DsTokens value as its fallback.
  var D = function (name, value) { return 'var(--ds-' + name + ',' + value + ')'; };
  var FONT = '"Pretendard",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Segoe UI",sans-serif';
  var TY = function (role, w, size) { return D('type-' + role, w + ' ' + size + ' ' + FONT); };
  var FG1 = D('fg-1', '#21242C'), FG2 = D('fg-2', '#3E424B'), FG3 = D('fg-3', '#5D616A'), FG4 = D('fg-4', '#6C707A'), FG_DIS = D('fg-disabled', '#B9BDC8');
  var FG_ON = D('fg-on-brand', '#FFFFFF'), FG_BRAND = D('fg-brand-1', '#4450CE'), FG_LINK = D('fg-link', '#3940BD');
  var FG2_BH = D('fg-2-brand-hover', '#4450CE'), FG2_BP = D('fg-2-brand-pressed', '#3940BD');
  var BG1 = D('bg-1', '#FFFFFF'), BG1_H = D('bg-1-hover', '#F6F8FD'), BG1_P = D('bg-1-pressed', '#DCE0EB'), BG3 = D('bg-3', '#F6F8FD'), BG5 = D('bg-5', '#E7EBF6');
  var BG_DIS = D('bg-disabled', '#EFF2FA'), SUB_H = D('subtle-bg-hover', '#F6F8FD'), SUB_P = D('subtle-bg-pressed', '#DCE0EB'), SUB_S = D('subtle-bg-selected', '#E7EBF6');
  var BRAND = D('brand-bg', '#4450CE'), BRAND_H = D('brand-bg-hover', '#3940BD'), BRAND_P = D('brand-bg-pressed', '#1D008B'), BRAND2 = D('brand-bg-2', '#E4EDFF');
  var CB = D('compound-brand', '#4450CE');
  var ST1 = D('stroke-1', '#CDD1DC'), ST1_H = D('stroke-1-hover', '#C3C7D2'), ST1_P = D('stroke-1-pressed', '#AFB3BE'), ST2 = D('stroke-2', '#DCE0EB');
  var ACC = D('stroke-accessible', '#5D616A'), ACC_H = D('stroke-accessible-hover', '#535760'), ST_DIS = D('stroke-disabled', '#DCE0EB');
  var INFO_BG = D('info-bg', '#F6F8FD'), INFO_BD = D('info-border', '#CDD1DC');
  var SH4 = D('shadow-4', '0 0 2px #1513520F, 0 2px 4px #15135224'), SH8 = D('shadow-8', '0 0 2px #1513520F, 0 4px 8px #15135224');
  var SH16 = D('shadow-16', '0 0 2px #1513520F, 0 8px 16px #15135224');
  var R_BTN = D('radius-button', '8px'), R_CARD = D('radius-product-card', '16px'), R_LIST = D('radius-listbox', '8px'), R_ITEM = D('radius-menu-item', '6px');
  var R4 = D('radius-4', '4px'), R8 = D('radius-8', '8px'), R12 = D('radius-12', '12px'), R16 = D('radius-16', '16px'), R_MB = D('radius-message-bar', '8px');
  var CAP2 = TY('caption-2', 400, '10px/14px'), CAP1 = TY('caption-1', 400, '12px/16px'), CAP1S = TY('caption-1-strong', 600, '12px/16px');
  var B1 = TY('body-1', 400, '14px/20px'), B1S = TY('body-1-strong', 600, '14px/20px'), SUB2 = TY('subtitle-2', 600, '16px/22px'), SUB1 = TY('subtitle-1', 600, '20px/28px');
  var T3 = TY('title-3', 400, '24px/32px'), LT = TY('large-title', 600, '40px/56px');
  // 정보 아이콘(메시지 바, NeutralForeground3) / the info icon (message bar, NeutralForeground3)
  var INFO_IC = 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 20 20%27%3E%3Ccircle cx=%2710%27 cy=%2710%27 r=%278%27 fill=%27%235D616A%27/%3E%3Cpath d=%27M10 9v5%27 stroke=%27white%27 stroke-width=%271.6%27 stroke-linecap=%27round%27/%3E%3Ccircle cx=%2710%27 cy=%276.4%27 r=%271%27 fill=%27white%27/%3E%3C/svg%3E")';
  var st = document.createElement('style');
  st.id = 'ai365WgCss';
  st.textContent = [
    '.ai365-wgs{display:flex;flex-direction:column;gap:12px;margin:16px 0 4px;}',
    '.ai365-wg{border:1px solid ' + ST2 + ';border-radius:' + R_CARD + ';background:' + BG1 + ';color:' + FG1 + ';font:' + B1 + ';overflow:hidden;}',
    '.ai365-wg button{font:inherit;color:inherit;cursor:pointer;}',
    '.ai365-wg-foot{font:' + CAP1 + ';color:' + FG3 + ';padding:0 20px 16px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;}',
    '.ai365-wg-foot a{color:inherit;text-decoration:underline;text-underline-offset:2px;}',
    '.ai365-wg-foot a:hover{color:' + FG_LINK + ';}',
    /* 날씨 / weather */
    '.ai365-wg-wx .wx-top{padding:20px 20px 4px;}',
    '.ai365-wg-wx .wx-loc{font:' + SUB2 + ';}',
    '.ai365-wg-wx .wx-now{display:flex;align-items:flex-start;gap:4px;margin-top:4px;}',
    '.ai365-wg-wx .wx-temp{font:' + LT + ';}',
    // °C/°F = DS Subtle 버튼 S(글자) / the °C/°F switch is a DS Subtle button S (text)
    '.ai365-wg-wx .wx-unit{font:' + CAP1 + ';color:' + FG3 + ';padding:2px 4px;border-radius:' + R4 + ';margin-top:10px;}',
    '.ai365-wg-wx .wx-unit:hover{background:' + SUB_H + ';}',
    '.ai365-wg-wx .wx-unit:active{background:' + SUB_P + ';}',
    '.ai365-wg-wx .wx-unit b{color:' + FG1 + ';font-weight:600;}',
    '.ai365-wg-wx .wx-desc{font:' + B1 + ';color:' + FG2 + ';margin-top:8px;}',
    '.ai365-wg-wx .wx-days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;padding:16px 20px 6px;}',
    // 날짜 칸 = DS Subtle 선택 단계(hover · pressed · selected, r8) / day cells follow the DS Subtle steps (hover, pressed, selected; r8)
    '.ai365-wg-wx .wx-day{display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px 0;border-radius:' + R_BTN + ';background:transparent;}',
    '.ai365-wg-wx .wx-day:hover{background:' + SUB_H + ';}',
    '.ai365-wg-wx .wx-day:active{background:' + SUB_P + ';}',
    '.ai365-wg-wx .wx-day.sel{background:' + SUB_S + ';}',
    '.ai365-wg-wx .wx-day .d{font:' + B1 + ';color:' + FG2 + ';}',
    '.ai365-wg-wx .wx-day .hi{font:' + SUB2 + ';}',
    '.ai365-wg-wx .wx-day .lo{font:' + B1 + ';color:' + FG3 + ';margin-top:-4px;}',
    '.ai365-wg-wx .wx-ic{width:24px;height:24px;display:block;}',
    // 그래프 종류 = DS Dropdown M(Outline 트리거 32 · r8, 열림 = 아래 2px 브랜드) + 목록(r8 · 안쪽 4 · Shadow 16, 항목 32 · r6)
    // The graph switch = a DS Dropdown M (Outline trigger, 32, r8; open = a 2px brand bottom line) with its list (r8, 4 padding, Shadow 16; 32px r6 options)
    '.ai365-wg-wx .wx-mode{position:relative;padding:8px 20px 0;}',
    '.ai365-wg-wx .wx-mode-btn{display:inline-flex;align-items:center;gap:6px;height:32px;font:' + B1 + ';color:' + FG1 + ';padding:0 8px 0 10px;border:1px solid ' + ST1 + ';border-bottom-color:' + ACC + ';border-radius:' + R_BTN + ';background:' + BG1 + ';transition:border-color .12s;}',
    '.ai365-wg-wx .wx-mode-btn svg{color:' + FG3 + ';}',
    '.ai365-wg-wx .wx-mode-btn:hover{border-color:' + ST1_H + ';border-bottom-color:' + ACC_H + ';}',
    '.ai365-wg-wx .wx-mode-btn[aria-expanded="true"]{border-bottom-color:' + CB + ';box-shadow:inset 0 -1px 0 ' + CB + ';}',
    '.ai365-wg-wx .wx-menu{position:absolute;left:20px;top:44px;z-index:5;background:' + BG1 + ';border:0;border-radius:' + R_LIST + ';box-shadow:' + SH16 + ';padding:4px;min-width:140px;display:flex;flex-direction:column;gap:2px;}',
    '.ai365-wg-wx .wx-menu button{display:block;width:100%;min-height:32px;text-align:left;font:' + B1 + ';color:' + FG2 + ';padding:6px 8px;border-radius:' + R_ITEM + ';}',
    '.ai365-wg-wx .wx-menu button:hover{background:' + SUB_H + ';color:' + FG1 + ';}',
    '.ai365-wg-wx .wx-menu button:active{background:' + SUB_P + ';}',
    '.ai365-wg-wx .wx-menu button.on{background:' + SUB_S + ';color:' + FG1 + ';}',
    '.ai365-wg-wx .wx-chart{padding:4px 12px 8px;}',
    '.ai365-wg-wx .wx-chart svg{width:100%;height:auto;display:block;}',
    /* 환율 / exchange rate (금액 = Title 3 / amounts = Title 3) */
    '.ai365-wg-fx .fx-row{padding:16px 20px;}',
    '.ai365-wg-fx .fx-row + .fx-row{border-top:1px solid ' + ST2 + ';margin:0 20px;padding-left:0;padding-right:0;}',
    '.ai365-wg-fx .fx-cur{font:' + B1 + ';color:' + FG2 + ';display:flex;gap:6px;align-items:center;}',
    '.ai365-wg-fx .fx-cc{font:' + CAP1S + ';color:' + FG3 + ';}',
    '.ai365-wg-fx .fx-amt{font:' + T3 + ';color:' + FG1 + ';margin-top:8px;}',
    /* 지도 카드(지도 바탕 #E8EEF2 는 지도 자리표시 색이라 그대로) / map card (the #E8EEF2 map backdrop is a map placeholder colour and stays) */
    '.ai365-wg-pl .pl-map{position:relative;height:410px;background:#E8EEF2;}',
    '.ai365-wg-pl .pl-canvas{position:absolute;inset:0;}',
    // 지도 위 [크게 보기] = DS Secondary 버튼 M(r8), 지도 위라 떠 있는 Shadow 04 / [Expand] over the map is a DS Secondary button M (r8) with a floating Shadow 04
    '.ai365-wg-pl .pl-expand{position:absolute;top:12px;right:12px;z-index:3;display:inline-flex;align-items:center;gap:6px;height:32px;background:' + BG1 + ';border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';padding:0 12px;font:' + B1S + ';color:' + FG1 + ';box-shadow:' + SH4 + ';}',
    '.ai365-wg-pl .pl-expand:hover{background:' + BG1_H + ';border-color:' + ST1_H + ';}',
    '.ai365-wg-pl .pl-expand:active{background:' + BG1_P + ';border-color:' + ST1_P + ';}',
    '.ai365-wg-pl .pl-cards{position:absolute;left:0;right:0;bottom:0;z-index:2;display:flex;gap:10px;overflow-x:auto;padding:12px 16px 16px;scrollbar-width:thin;}',
    '.ai365-wg-pl.no-map .pl-map{height:auto;background:' + BG3 + ';}',
    '.ai365-wg-pl.no-map .pl-canvas{display:none;}',
    '.ai365-wg-pl.no-map .pl-cards{position:static;flex-wrap:wrap;overflow:visible;}',
    // 지도 안내 = DS 메시지 바(정보: 회색 바탕 · 선 · 아이콘, r8) / the map note is a DS message bar (info: grey ground, stroke and icon; r8)
    '.ai365-wg-pl .pl-note{position:absolute;inset:12px 16px auto 16px;z-index:3;min-height:36px;display:flex;align-items:center;padding:8px 12px 8px 38px;font:' + CAP1 + ';color:' + FG1 + ';background:' + INFO_BG + ' ' + INFO_IC + ' no-repeat 12px center/18px;border:1px solid ' + INFO_BD + ';border-radius:' + R_MB + ';}',
    // 목록만 보일 때: 안내 막대 오른쪽에 [크게 보기] 자리를 비우고 둘의 가운데 높이를 맞춘다 / list-only: keep room for [Expand] right of the bar and centre the two
    '.ai365-wg-pl.no-map .pl-map{padding-top:12px;}',   // 막대 위 여백은 상자 안쪽(바깥 여백은 겹쳐 사라진다) / the gap above the bar is padding (an outer margin would collapse)
    '.ai365-wg-pl.no-map .pl-note{position:static;margin:0 128px 0 16px;}',
    '.ai365-wg-pl.no-map .pl-expand{top:14px;right:16px;}',
    // 장소 카드 = DS Card(흰 바탕 · r8, 지도 위 Shadow 04 → hover Background 1 hover + Shadow 08) / place cards = DS Cards (white, r8; over the map Shadow 04, hover Background 1 hover + Shadow 08)
    '.ai365-wg-pl .pl-card,.ai365-mapx .mx-item{display:flex;gap:12px;align-items:center;text-align:left;background:' + BG1 + ';border-radius:' + R8 + ';padding:10px 12px;}',
    '.ai365-wg-pl .pl-card{flex:0 0 250px;box-shadow:' + SH4 + ';transition:box-shadow .12s,background .12s;}',
    '.ai365-wg-pl .pl-card:hover{background:' + BG1_H + ';box-shadow:' + SH8 + ';}',
    '.ai365-wg-pl .pl-card:active{background:' + BG1_P + ';}',
    '.ai365-mapx .mx-item:hover{background:' + SUB_H + ';}',
    '.ai365-mapx .mx-item:active{background:' + SUB_P + ';}',
    '.ai365-mapx .mx-item.sel{background:' + SUB_S + ';}',
    '.ai365-wg-ph{flex:0 0 56px;width:56px;height:56px;border-radius:' + R8 + ';background:' + BG5 + ' center/cover no-repeat;display:flex;align-items:center;justify-content:center;color:' + FG4 + ';}',
    '.ai365-wg-tx{min-width:0;display:flex;flex-direction:column;gap:2px;}',
    '.ai365-wg-tx .nm{font:' + B1S + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.ai365-wg-tx .mt{font:' + CAP1 + ';color:' + FG2 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.ai365-wg-tx .pr{font:' + CAP1 + ';color:' + FG3 + ';}',
    '.ai365-wg-pl .pl-stale{display:flex;gap:12px;align-items:center;padding:16px 20px;}',
    '.ai365-wg-pl .pl-stale .ic{flex:0 0 40px;height:40px;border-radius:' + R12 + ';background:' + BRAND2 + ';color:' + CB + ';display:flex;align-items:center;justify-content:center;}',
    '.ai365-wg-pl .pl-stale .tx{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}',
    '.ai365-wg-pl .pl-stale .tx b{font:' + B1S + ';}',
    '.ai365-wg-pl .pl-stale .tx span{font:' + CAP1 + ';color:' + FG3 + ';}',
    // 버튼 = DS 코어 버튼 M(r8 · 32 · Body 1 Strong): 기본 Secondary(흰 바탕 · Stroke 1 → hover · pressed 중립 단계), .pri = Primary, 비활성 = DS 비활성 색
    // Buttons = DS core buttons M (r8, 32, Body 1 Strong): Secondary by default (white, Stroke 1, neutral hover and pressed steps), .pri = Primary, disabled = the DS disabled colours
    '.ai365-wg-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:32px;border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';background:' + BG1 + ';padding:5px 12px;font:' + B1S + ';white-space:nowrap;color:' + FG1 + ';text-decoration:none;transition:background .12s,border-color .12s;}',
    '.ai365-wg-btn:hover{background:' + BG1_H + ';border-color:' + ST1_H + ';}',
    '.ai365-wg-btn:active{background:' + BG1_P + ';border-color:' + ST1_P + ';}',
    '.ai365-wg-btn.pri{min-width:96px;background:' + BRAND + ';border-color:transparent;color:' + FG_ON + ';}',
    '.ai365-wg-btn.pri:hover{background:' + BRAND_H + ';border-color:transparent;}',
    '.ai365-wg-btn.pri:active{background:' + BRAND_P + ';border-color:transparent;}',
    '.ai365-wg-btn[disabled],.ai365-wg-btn[disabled]:hover{cursor:default;background:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
    '.ai365-wg-btn.pri[disabled],.ai365-wg-btn.pri[disabled]:hover{background:' + BG_DIS + ';border-color:transparent;color:' + FG_DIS + ';}',
    /* 핀(지도 위 표식 = 데이터 색, 그대로) / pins (markers on the map are data colours and stay) */
    '.ai365-wg-pin{display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;transform:translateY(50%);}',
    '.ai365-wg-pin .b{display:inline-flex;align-items:center;gap:3px;background:#fff;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:600;color:#1F2430;box-shadow:0 1px 4px rgba(20,23,32,.28);}',
    '.ai365-wg-pin .b svg{width:11px;height:11px;}',
    '.ai365-wg-pin .n{font-size:12px;font-weight:600;color:#1F2430;max-width:140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 0 3px #fff,0 0 3px #fff,0 0 3px #fff;}',
    '.ai365-wg-pin:hover .b{box-shadow:0 2px 8px rgba(20,23,32,.35);}',
    '.ai365-wg-pin.sel .b{background:#2E2A86;color:#fff;}',
    /* 크게 보기 / expanded view */
    '.ai365-mapx{position:absolute;inset:0;z-index:70;background:#E8EEF2;}',
    '.ai365-mapx .mx-map{position:absolute;inset:0;}',
    // 지도 없음 안내 = DS 메시지 바(정보), 지도 조작 버튼 오른쪽에 둔다(전에는 버튼 밑에 깔렸다) / the no-map note = a DS message bar (info), placed right of the map controls (it used to sit under them)
    '.ai365-mapx .mx-nomap{position:absolute;left:72px;top:16px;right:440px;min-height:36px;display:flex;align-items:center;padding:8px 12px 8px 38px;font:' + CAP1 + ';color:' + FG1 + ';background:' + INFO_BG + ' ' + INFO_IC + ' no-repeat 12px center/18px;border:1px solid ' + INFO_BD + ';border-radius:' + R_MB + ';}',
    '.ai365-mapx .mx-ctrl{position:absolute;left:16px;top:16px;z-index:3;display:flex;flex-direction:column;gap:8px;align-items:center;}',
    // 지도 조작 = DS Secondary 아이콘 버튼 L(40 · r8), 지도 위라 Shadow 04 / map controls = DS Secondary icon buttons L (40, r8) with Shadow 04 over the map
    '.ai365-mapx .mx-btn{width:40px;height:40px;border-radius:' + R_BTN + ';background:' + BG1 + ';border:1px solid ' + ST1 + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';box-shadow:' + SH4 + ';}',
    '.ai365-mapx .mx-btn:hover{background:' + BG1_H + ';border-color:' + ST1_H + ';color:' + FG2_BH + ';}',
    '.ai365-mapx .mx-btn:active{background:' + BG1_P + ';border-color:' + ST1_P + ';color:' + FG2_BP + ';}',
    '.ai365-mapx .mx-zoom{display:flex;flex-direction:column;background:' + BG1 + ';border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';box-shadow:' + SH4 + ';overflow:hidden;}',
    '.ai365-mapx .mx-zoom button{width:40px;height:38px;display:flex;align-items:center;justify-content:center;color:' + FG2 + ';}',
    '.ai365-mapx .mx-zoom button:hover{background:' + BG1_H + ';color:' + FG2_BH + ';}',
    '.ai365-mapx .mx-zoom button:active{background:' + BG1_P + ';color:' + FG2_BP + ';}',
    '.ai365-mapx .mx-zoom button + button{border-top:1px solid ' + ST2 + ';}',
    // 옆 패널 = 떠 있는 패널(흰 바탕 · r16 · Shadow 16) / the side panel floats (white, r16, Shadow 16)
    '.ai365-mapx .mx-side{position:absolute;top:16px;right:16px;bottom:16px;width:400px;max-width:calc(100% - 96px);z-index:3;background:' + BG1 + ';border-radius:' + R16 + ';box-shadow:' + SH16 + ';display:flex;flex-direction:column;overflow:hidden;}',
    '.ai365-mapx .mx-head{display:flex;align-items:center;justify-content:space-between;padding:12px 12px 12px 16px;border-bottom:1px solid ' + ST2 + ';font:' + SUB2 + ';color:' + FG1 + ';}',
    // 아이콘 버튼 = DS Subtle 아이콘 버튼 M(32 · r8, hover 아이콘 브랜드) / icon buttons = DS Subtle icon buttons M (32, r8; the icon turns brand on hover)
    '.ai365-mapx .mx-head button{width:32px;height:32px;border-radius:' + R_BTN + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';}',
    '.ai365-mapx .mx-head button:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
    '.ai365-mapx .mx-head button:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
    '.ai365-mapx .mx-body{flex:1;overflow-y:auto;padding:12px 16px 16px;}',
    '.ai365-mapx .mx-list{display:flex;flex-direction:column;gap:2px;}',
    '.ai365-mapx .mx-item{width:100%;}',
    '.ai365-mapx .mx-more{display:flex;margin:12px 0 0;width:100%;}',
    // 핀 팝업 = DS 팝오버(흰 바탕 · r12 · Shadow 16) / the pin popup is a DS popover (white, r12, Shadow 16)
    '.ai365-mapx .mx-pop{position:absolute;z-index:4;width:260px;background:' + BG1 + ';border-radius:' + R12 + ';box-shadow:' + SH16 + ';padding:12px;display:none;}',
    '.ai365-mapx .mx-pop.on{display:block;}',
    '.ai365-mapx .mx-pop .row{display:flex;gap:10px;align-items:center;}',
    '.ai365-mapx .mx-pop .acts{display:flex;gap:8px;margin-top:10px;}',
    '.ai365-mapx .mx-pop .acts .ai365-wg-btn{flex:1;}',
    '.ai365-mapx .mx-dt .mx-hero{width:100%;height:200px;border-radius:' + R8 + ';background:' + BG5 + ' center/cover no-repeat;position:relative;}',
    '.ai365-mapx .mx-dt .credit{position:absolute;right:8px;bottom:6px;font:' + CAP2 + ';color:#fff;text-shadow:0 0 3px rgba(0,0,0,.7);max-width:80%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.ai365-mapx .mx-dt .credit a{color:inherit;}',
    '.ai365-mapx .mx-dt h3{font:' + SUB1 + ';margin:16px 0 4px;}',
    '.ai365-mapx .mx-dt .meta{font:' + CAP1 + ';color:' + FG2 + ';display:flex;align-items:center;gap:4px;}',
    '.ai365-mapx .mx-dt .acts{display:flex;gap:8px;margin:12px 0 6px;}',
    '.ai365-mapx .mx-dt .acts .ai365-wg-btn{flex:1;}',
    '.ai365-mapx .mx-dt .line{display:flex;gap:10px;align-items:flex-start;padding:10px 0;font:' + B1 + ';color:' + FG1 + ';}',
    '.ai365-mapx .mx-dt .line svg{flex:0 0 16px;margin-top:2px;color:' + FG3 + ';}',
    '.ai365-mapx .mx-dt .line .grow{flex:1;min-width:0;}',
    '.ai365-mapx .mx-dt .hours-btn{display:flex;width:100%;justify-content:space-between;align-items:center;text-align:left;}',
    '.ai365-mapx .mx-dt .hours{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;padding:8px 0 2px;font:' + CAP1 + ';color:' + FG2 + ';}',
    '.ai365-mapx .mx-dt .hours[hidden]{display:none;}',
    '.ai365-mapx .mx-dt .copyable{display:flex;gap:6px;align-items:center;}',
    '.ai365-mapx .mx-dt .copy-ic{opacity:0;width:24px;height:24px;border-radius:' + R_BTN + ';display:inline-flex;align-items:center;justify-content:center;color:' + FG2 + ';}',
    '.ai365-mapx .mx-dt .copy-ic:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
    '.ai365-mapx .mx-dt .copyable:hover .copy-ic{opacity:1;}',
    '.ai365-mapx .mx-dt .copyable:hover .tx{color:' + FG_BRAND + ';}',
    '.ai365-mapx .mx-dt .about{font:' + B1 + ';color:' + FG1 + ';margin:10px 0 4px;}',
    '.ai365-mapx .mx-dt h4{font:' + SUB2 + ';margin:16px 0 8px;}',
    '.ai365-mapx .mx-dt .rv{padding:10px 0;border-top:1px solid ' + ST2 + ';}',
    '.ai365-mapx .mx-dt .rv-h{display:flex;gap:8px;align-items:center;font:' + CAP1 + ';color:' + FG2 + ';}',
    '.ai365-mapx .mx-dt .rv-h img{width:24px;height:24px;border-radius:50%;}',
    '.ai365-mapx .mx-dt .rv-h a{color:' + FG1 + ';font-weight:600;text-decoration:none;}',
    '.ai365-mapx .mx-dt .rv-t{font:' + B1 + ';margin-top:6px;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}',
    '.ai365-mapx .mx-dt .rv-more{display:inline-block;font:' + CAP1 + ';color:' + FG_LINK + ';margin-top:6px;}',
    '.ai365-mapx .mx-dt .foot{display:flex;gap:6px;padding:12px 0 0;}',
    '.ai365-mapx .mx-dt .foot button{width:32px;height:32px;border-radius:' + R_BTN + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';}',
    '.ai365-mapx .mx-dt .foot button:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
    '.ai365-mapx .mx-dt .foot button:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
    '.ai365-mapx .mx-dt .muted{color:' + FG3 + ';font:' + CAP1 + ';}'
  ].join('');
  document.head.appendChild(st);
})();

/* 라벨 KO/EN — 채팅 본문은 번역 루트 밖이라 렌더할 때 고른다 / labels picked at render time (the chat body is outside the translation roots) */
var AI365_WG_T = {
  ko: { expand: '크게 보기', places: '{n}개의 장소', more: '더 많은 장소 보기', less: '더 적게 보기', info: '가게 정보',
        route: '경로', call: '전화', web: '웹사이트', reviews: '이용후기', moreReviews: 'Google 지도에서 후기 더 보기',
        reload: '지도 다시 불러오기', staleTitle: '‘{q}’ 장소 {n}곳', staleSub: '구글 정책상 장소 정보는 저장하지 않아, 다시 불러와야 지도로 볼 수 있어요.',
        temp: '온도', pop: '강수 확률', asOf: '기준', noMap: '지도를 불러오지 못해 목록만 보여 드려요.',
        quota: '이번 달 무료 지도 사용량을 다 써서 목록만 보여 드려요.', noKey: '구글 지도 키가 없어 목록만 보여 드려요.',
        photo: '사진', copy: '복사', copied: '복사했어요', close: '닫기', zoomIn: '확대', zoomOut: '축소', reset: '원위치',
        loading: '불러오는 중…', failed: '정보를 불러오지 못했어요.', noReviews: '등록된 후기가 없어요.', back: '목록으로',
        quotaDetail: '이번 달 무료 사용량을 다 써서 가게 정보를 불러올 수 없어요.', googleMaps: 'Google 지도', more1: '더 보기' },
  en: { expand: 'Expand', places: '{n} places', more: 'Show more places', less: 'Show fewer', info: 'Place info',
        route: 'Directions', call: 'Call', web: 'Website', reviews: 'Reviews', moreReviews: 'More reviews on Google Maps',
        reload: 'Reload map', staleTitle: '“{q}” · {n} places', staleSub: 'Place data is not stored (Google policy). Reload to see the map again.',
        temp: 'Temperature', pop: 'Chance of rain', asOf: '', noMap: 'The map could not load, so here is the list.',
        quota: "This month's free map allowance is used up, so here is the list.", noKey: 'No Google Maps key is set, so here is the list.',
        photo: 'Photo', copy: 'Copy', copied: 'Copied', close: 'Close', zoomIn: 'Zoom in', zoomOut: 'Zoom out', reset: 'Reset view',
        loading: 'Loading…', failed: 'Could not load the details.', noReviews: 'No reviews yet.', back: 'Back to list',
        quotaDetail: "This month's free allowance is used up, so details can't load.", googleMaps: 'Google Maps', more1: 'More' }
};

function ai365WgLang() {
  return (typeof ai365CurrentLang === 'function' && ai365CurrentLang() === 'en') ? 'en' : 'ko';
}

function ai365WgT(key, vars) {
  var s = (AI365_WG_T[ai365WgLang()] || AI365_WG_T.ko)[key] || AI365_WG_T.ko[key] || '';
  Object.keys(vars || {}).forEach(function (k) { s = s.split('{' + k + '}').join(String(vars[k])); });
  return s;
}

function ai365WgEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function ai365WgUrl(u) {
  var s = String(u || '');
  return /^https:\/\//i.test(s) ? ai365WgEsc(s) : '';
}

/* KST 표시 — kst.js 가 있으면 그걸로, 없으면(단독 테스트) 문자열에서 / KST display via kst.js, else from the string */
function ai365WgWhen(iso, kind) {
  if (typeof ai365KstFmt === 'function') return ai365KstFmt(iso, kind, ai365WgLang());
  var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(iso || ''));
  return m ? (kind === 'hm' ? m[4] + ':' + m[5] : m[1] + '-' + m[2] + '-' + m[3] + ' ' + m[4] + ':' + m[5]) : '';
}

function ai365WgNowParts() {
  if (typeof ai365KstParts === 'function') return ai365KstParts();
  var d = new Date();
  return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate(), h: d.getHours(), mi: d.getMinutes() };
}

var AI365_WG_ICON = {
  sunny: '<svg viewBox="0 0 32 32" class="wx-ic"><circle cx="16" cy="16" r="6.5" fill="#F7A823"/><g stroke="#F7A823" stroke-width="2.2" stroke-linecap="round"><path d="M16 3.5v3M16 25.5v3M3.5 16h3M25.5 16h3M7.2 7.2l2.1 2.1M22.7 22.7l2.1 2.1M7.2 24.8l2.1-2.1M22.7 9.3l2.1-2.1"/></g></svg>',
  partly: '<svg viewBox="0 0 32 32" class="wx-ic"><circle cx="12" cy="12" r="5.5" fill="#F7A823"/><g stroke="#F7A823" stroke-width="2" stroke-linecap="round"><path d="M12 2.5v2.4M2.5 12h2.4M5.3 5.3l1.7 1.7M18.7 5.3l-1.7 1.7"/></g><path d="M10.5 26.5h13.2a5 5 0 0 0 .4-10 6.6 6.6 0 0 0-12.6 1.8 4.1 4.1 0 0 0-1 8.2z" fill="#DCE3EE"/></svg>',
  mostly: '<svg viewBox="0 0 32 32" class="wx-ic"><circle cx="21.5" cy="10" r="4.6" fill="#F7A823"/><path d="M8 26.5h14.6a5.6 5.6 0 0 0 .6-11.2 7.4 7.4 0 0 0-14.1 2 4.6 4.6 0 0 0-1.1 9.2z" fill="#C9D3E2"/></svg>',
  cloudy: '<svg viewBox="0 0 32 32" class="wx-ic"><path d="M8 25.5h15.2a5.8 5.8 0 0 0 .7-11.6 7.6 7.6 0 0 0-14.6 2.1A4.8 4.8 0 0 0 8 25.5z" fill="#BAC4D4"/></svg>',
  rain: '<svg viewBox="0 0 32 32" class="wx-ic"><path d="M16 5.5c-6.4 0-11.4 4.6-11.9 10.6h23.8C27.4 10.1 22.4 5.5 16 5.5z" fill="#6EA8F5"/><path d="M16 16v8.6a2.6 2.6 0 0 1-5.2 0" fill="none" stroke="#6EA8F5" stroke-width="2.2" stroke-linecap="round"/><path d="M16 3.8v1.9" stroke="#6EA8F5" stroke-width="2.2" stroke-linecap="round"/></svg>',
  shower: '<svg viewBox="0 0 32 32" class="wx-ic"><path d="M8 19.5h15.2a5.6 5.6 0 0 0 .7-11.2 7.4 7.4 0 0 0-14.2 2A4.6 4.6 0 0 0 8 19.5z" fill="#C3CCDA"/><g stroke="#6EA8F5" stroke-width="2" stroke-linecap="round"><path d="M11 23l-1.2 3M16 23l-1.2 3M21 23l-1.2 3"/></g></svg>',
  snow: '<svg viewBox="0 0 32 32" class="wx-ic"><path d="M8 18.5h15.2a5.6 5.6 0 0 0 .7-11.2 7.4 7.4 0 0 0-14.2 2A4.6 4.6 0 0 0 8 18.5z" fill="#C3CCDA"/><g fill="#8DB9F5"><circle cx="11" cy="23.5" r="1.7"/><circle cx="16" cy="26" r="1.7"/><circle cx="21" cy="23.5" r="1.7"/></g></svg>',
  thunder: '<svg viewBox="0 0 32 32" class="wx-ic"><path d="M8 18.5h15.2a5.6 5.6 0 0 0 .7-11.2 7.4 7.4 0 0 0-14.2 2A4.6 4.6 0 0 0 8 18.5z" fill="#BAC4D4"/><path d="M16.8 16.5l-4.3 7h3.6l-1.4 5.3 5.1-7.6h-3.7l1.6-4.7z" fill="#F7C531"/></svg>'
};

/* WMO 코드 → [아이콘, 한국어, 영어] (서버 app/live_weather.WMO 와 같은 표) / WMO code → [icon, ko, en] (same table as the server) */
var AI365_WG_WMO = {
  0: ['sunny', '맑음', 'Clear'], 1: ['partly', '구름 조금', 'Mostly sunny'], 2: ['mostly', '구름 많음', 'Partly cloudy'],
  3: ['cloudy', '흐림', 'Cloudy'], 45: ['cloudy', '안개', 'Fog'], 48: ['cloudy', '안개', 'Fog'],
  51: ['rain', '이슬비', 'Drizzle'], 53: ['rain', '이슬비', 'Drizzle'], 55: ['rain', '이슬비', 'Drizzle'],
  56: ['rain', '어는 이슬비', 'Freezing drizzle'], 57: ['rain', '어는 이슬비', 'Freezing drizzle'],
  61: ['rain', '약한 비', 'Light rain'], 63: ['rain', '비', 'Rain'], 65: ['rain', '강한 비', 'Heavy rain'],
  66: ['rain', '어는 비', 'Freezing rain'], 67: ['rain', '어는 비', 'Freezing rain'],
  71: ['snow', '약한 눈', 'Light snow'], 73: ['snow', '눈', 'Snow'], 75: ['snow', '많은 눈', 'Heavy snow'], 77: ['snow', '싸락눈', 'Snow grains'],
  80: ['shower', '약한 소나기', 'Light showers'], 81: ['shower', '소나기', 'Showers'], 82: ['shower', '강한 소나기', 'Heavy showers'],
  85: ['snow', '소낙눈', 'Snow showers'], 86: ['snow', '소낙눈', 'Snow showers'],
  95: ['thunder', '뇌우', 'Thunderstorm'], 96: ['thunder', '우박 동반 뇌우', 'Thunderstorm with hail'], 99: ['thunder', '우박 동반 뇌우', 'Thunderstorm with hail']
};

function ai365WgWmo(code) {
  return AI365_WG_WMO[code] || ['cloudy', '흐림', 'Cloudy'];
}

/* 위젯 꽂기 — 답변 본문 바로 뒤(라이브 done · 복원 공용) / insert widgets right after the answer body (live done and restore) */
function ai365WgInsert(bodyEl, cards) {
  if (!bodyEl || !cards || !cards.length || !bodyEl.parentNode) return;
  var list = cards.filter(function (c) { return c && (c.kind === 'weather' || c.kind === 'fx' || c.kind === 'places'); });
  if (!list.length) return;
  var holder = document.createElement('div');
  holder.className = 'ai365-wgs';
  list.forEach(function (c) {
    var el = null;
    try {
      if (c.kind === 'weather') el = ai365WgWeatherEl(c);
      else if (c.kind === 'fx') el = ai365WgFxEl(c);
      else el = c.items ? ai365WgPlacesEl(c) : ai365WgPlacesStaleEl(c);
    } catch (e) { console.warn('[AI365 widget] 렌더 실패 / render failed', e); }
    if (el) holder.appendChild(el);
  });
  if (holder.childNodes.length) bodyEl.insertAdjacentElement('afterend', holder);
}

/* ───────────── 날씨 / weather ───────────── */
function ai365WgDow(date, lang) {
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(date || ''));
  if (!m) return '';
  var w = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay();
  return (lang === 'en' ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] : ['일', '월', '화', '수', '목', '금', '토'])[w];
}

function ai365WgTemp(c, unit) {
  if (c === null || c === undefined || c === '') return '-';
  var v = unit === 'F' ? (+c) * 9 / 5 + 32 : +c;
  return Math.round(v) + '°';
}

function ai365WgHourLabel(iso) {
  var h = +String(iso).slice(11, 13);
  var h12 = (h % 12) || 12;
  return h12 + (h < 12 ? 'am' : 'pm');
}

/* 고른 날의 시간 창 — 오늘은 지금 시각부터 24시간, 다른 날은 0시부터 / the hour window: from now for today, from 0h otherwise */
function ai365WgWindow(card, dayIdx) {
  var h = card.hourly || {}, times = h.time || [];
  var day = (card.days || [])[dayIdx];
  if (!day || !times.length) return { idx: [] };
  var start;
  if (dayIdx === 0) {
    var p = ai365WgNowParts();
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var key = day.date + 'T' + pad(p.h) + ':00';
    start = times.indexOf(key);
    if (start < 0) start = times.indexOf(day.date + 'T00:00');
  } else {
    start = times.indexOf(day.date + 'T00:00');
  }
  if (start < 0) start = 0;
  var idx = [];
  for (var i = start; i < Math.min(times.length, start + 24); i++) idx.push(i);
  return { idx: idx };
}

/* 시간별 그래프 SVG — mode 'temp' = 3시간 간격 8점 꺾은선, 'pop' = 24개 막대(라벨은 3시간마다)
   Hourly chart SVG — 'temp' = an 8-point line at 3-hour steps, 'pop' = 24 bars (labels every 3 hours) */
function ai365WgChartSvg(card, dayIdx, mode, unit) {
  var h = card.hourly || {}, win = ai365WgWindow(card, dayIdx).idx;
  var W = 720, H = 168, L = 28, R = 28, T = 30, B = 30;
  if (!win.length) return '<svg viewBox="0 0 ' + W + ' ' + H + '"></svg>';
  // 두 모드가 같은 x 축(시간 창의 j 번째 시각)을 쓴다 — 라벨이 막대 · 점과 맞는다 / both modes share one x scale so labels align
  var span = (W - L - R) / Math.max(1, win.length - 1);
  var xAt = function (j) { return L + j * span; };
  var tickJ = win.map(function (_, j) { return j; }).filter(function (j) { return j % 3 === 0; }).slice(0, 8);
  var ticks = tickJ.map(function (j) { return win[j]; });
  var xOf = function (k) { return xAt(tickJ[k]); };
  var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + ai365WgEsc(mode === 'pop' ? ai365WgT('pop') : ai365WgT('temp')) + '">';
  var labels = ticks.map(function (i, k) {
    return '<text x="' + xOf(k).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="13" fill="#6B7180">' + ai365WgHourLabel(h.time[i]) + '</text>';
  }).join('');
  if (mode === 'pop') {
    var bw = Math.max(4, span - 4);
    var base = H - B, top = T;
    win.forEach(function (i, j) {
      var v = Math.max(0, Math.min(100, +(h.pop || [])[i] || 0));
      var bh = Math.max(2, (base - top) * v / 100);
      var x = xAt(j) - bw / 2;
      out += '<rect x="' + x.toFixed(1) + '" y="' + (base - bh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="2" fill="#4F5BD5"' + (v ? '' : ' fill-opacity=".35"') + '/>';
    });
    ticks.forEach(function (i, k) {
      var v = Math.max(0, Math.min(100, +(h.pop || [])[i] || 0));
      var bh = Math.max(2, (base - top) * v / 100);
      out += '<text x="' + xOf(k).toFixed(1) + '" y="' + (base - bh - 6).toFixed(1) + '" text-anchor="middle" font-size="12" fill="#4B5263">' + Math.round(v) + '%</text>';
    });
    return out + labels + '</svg>';
  }
  var vals = ticks.map(function (i) { var c = (h.t || [])[i]; return c === null || c === undefined ? null : (unit === 'F' ? c * 9 / 5 + 32 : +c); });
  var real = vals.filter(function (v) { return v !== null; });
  if (!real.length) return out + labels + '</svg>';
  var lo = Math.min.apply(null, real), hi = Math.max.apply(null, real);
  if (hi - lo < 4) { hi += 2; lo -= 2; }
  var yOf = function (v) { return T + 12 + (H - T - B - 18) * (1 - (v - lo) / (hi - lo)); };
  var pts = vals.map(function (v, k) { return v === null ? null : [xOf(k), yOf(v)]; }).filter(Boolean);
  var line = pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
  var gid = 'wxg' + Math.random().toString(36).slice(2, 8);
  out += '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F59E0B" stop-opacity=".18"/><stop offset="1" stop-color="#F59E0B" stop-opacity="0"/></linearGradient></defs>';
  out += '<polygon points="' + pts[0][0].toFixed(1) + ',' + (H - B) + ' ' + line + ' ' + pts[pts.length - 1][0].toFixed(1) + ',' + (H - B) + '" fill="url(#' + gid + ')"/>';
  out += '<polyline points="' + line + '" fill="none" stroke="#F08C00" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>';
  vals.forEach(function (v, k) {
    if (v === null) return;
    out += '<circle cx="' + xOf(k).toFixed(1) + '" cy="' + yOf(v).toFixed(1) + '" r="4" fill="#F08C00"/>'
      + '<text x="' + xOf(k).toFixed(1) + '" y="' + (yOf(v) - 10).toFixed(1) + '" text-anchor="middle" font-size="13" fill="#3B4150">' + Math.round(v) + '°</text>';
  });
  return out + labels + '</svg>';
}

function ai365WgWeatherEl(card) {
  var lang = ai365WgLang();
  var st = { unit: 'C', mode: 'temp', day: Math.max(0, Math.min(+card.selected || 0, (card.days || []).length - 1)) };
  var el = document.createElement('div');
  el.className = 'ai365-wg ai365-wg-wx';
  el.setAttribute('data-wg', 'weather');
  function paint() {
    var now = card.now || {}, w = ai365WgWmo(now.code);
    var days = (card.days || []).map(function (d, i) {
      var dw = ai365WgWmo(d.code);
      return '<button type="button" class="wx-day' + (i === st.day ? ' sel' : '') + '" data-day="' + i + '" title="' + ai365WgEsc(lang === 'en' ? dw[2] : dw[1]) + '">'
        + '<span class="d">' + ai365WgDow(d.date, lang) + '</span>' + (AI365_WG_ICON[dw[0]] || '')
        + '<span class="hi">' + ai365WgTemp(d.max, st.unit) + '</span><span class="lo">' + ai365WgTemp(d.min, st.unit) + '</span></button>';
    }).join('');
    var unitBtn = st.unit === 'C' ? '<b>C</b>/F' : '<b>F</b>/C';
    var when = card.fetched_at ? ai365WgWhen(card.fetched_at, 'md') + ' ' + ai365WgWhen(card.fetched_at, 'hm') + (lang === 'en' ? '' : ' ' + ai365WgT('asOf')) : '';
    el.innerHTML = '<div class="wx-top"><div class="wx-loc">' + ai365WgEsc(card.location || '') + '</div>'
      + '<div class="wx-now"><span class="wx-temp">' + ai365WgTemp(now.t, st.unit) + '</span><button type="button" class="wx-unit" data-unit title="°C / °F">' + unitBtn + '</button></div>'
      + '<div class="wx-desc">' + ai365WgEsc(lang === 'en' ? w[2] : w[1]) + '</div></div>'
      + '<div class="wx-days">' + days + '</div>'
      + '<div class="wx-mode"><button type="button" class="wx-mode-btn" data-mode aria-expanded="false">' + ai365WgEsc(ai365WgT(st.mode === 'pop' ? 'pop' : 'temp'))
      + ' <svg width="10" height="14" viewBox="0 0 10 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 5l3-3 3 3M2 9l3 3 3-3"/></svg></button></div>'
      + '<div class="wx-chart">' + ai365WgChartSvg(card, st.day, st.mode, st.unit) + '</div>'
      + '<div class="ai365-wg-foot"><a href="' + ai365WgUrl((card.source || {}).url) + '" target="_blank" rel="noopener">' + ai365WgEsc((card.source || {}).name || 'Open-Meteo') + '</a>'
      + (when ? '<span>· ' + ai365WgEsc(when) + '</span>' : '') + '</div>';
  }
  el.addEventListener('click', function (e) {
    var t = e.target.closest('button');
    if (!t || !el.contains(t)) { closeMenu(); return; }
    if (t.hasAttribute('data-day')) { st.day = +t.getAttribute('data-day'); paint(); return; }
    if (t.hasAttribute('data-unit')) { st.unit = st.unit === 'C' ? 'F' : 'C'; paint(); return; }
    if (t.hasAttribute('data-mode')) {
      var open = el.querySelector('.wx-menu');
      if (open) { closeMenu(); return; }
      var m = document.createElement('div');
      m.className = 'wx-menu';
      m.innerHTML = '<button type="button" data-set="temp" class="' + (st.mode === 'temp' ? 'on' : '') + '">' + ai365WgEsc(ai365WgT('temp')) + '</button>'
        + '<button type="button" data-set="pop" class="' + (st.mode === 'pop' ? 'on' : '') + '">' + ai365WgEsc(ai365WgT('pop')) + '</button>';
      t.setAttribute('aria-expanded', 'true');
      t.parentNode.appendChild(m);
      return;
    }
    if (t.hasAttribute('data-set')) { st.mode = t.getAttribute('data-set'); paint(); }
  });
  function closeMenu() {
    var m = el.querySelector('.wx-menu');
    if (m) m.remove();
    var b = el.querySelector('[data-mode]');
    if (b) b.setAttribute('aria-expanded', 'false');
  }
  paint();
  return el;
}

/* ───────────── 환율 / exchange rate ───────────── */
var AI365_WG_CCY = {
  KRW: ['KR', '대한민국 원', 'South Korean won', '₩'], USD: ['US', '미국 달러', 'US dollar', '$'], JPY: ['JP', '일본 엔', 'Japanese yen', '¥'],
  EUR: ['EU', '유로', 'Euro', '€'], CNY: ['CN', '중국 위안', 'Chinese yuan', '¥'], GBP: ['GB', '영국 파운드', 'British pound', '£'],
  HKD: ['HK', '홍콩 달러', 'Hong Kong dollar', 'HK$'], TWD: ['TW', '대만 달러', 'New Taiwan dollar', 'NT$'], SGD: ['SG', '싱가포르 달러', 'Singapore dollar', 'S$'],
  AUD: ['AU', '호주 달러', 'Australian dollar', 'A$'], CAD: ['CA', '캐나다 달러', 'Canadian dollar', 'C$'], NZD: ['NZ', '뉴질랜드 달러', 'New Zealand dollar', 'NZ$'],
  CHF: ['CH', '스위스 프랑', 'Swiss franc', 'CHF'], VND: ['VN', '베트남 동', 'Vietnamese dong', '₫'], THB: ['TH', '태국 바트', 'Thai baht', '฿'],
  PHP: ['PH', '필리핀 페소', 'Philippine peso', '₱'], INR: ['IN', '인도 루피', 'Indian rupee', '₹'], IDR: ['ID', '인도네시아 루피아', 'Indonesian rupiah', 'Rp'],
  MYR: ['MY', '말레이시아 링깃', 'Malaysian ringgit', 'RM'], MXN: ['MX', '멕시코 페소', 'Mexican peso', 'MX$']
};

/* 카드 금액 — 100 이상은 정수, 1 이상은 소수 둘째, 1 미만은 유효 4자리 / card amounts: integers from 100, 2 decimals from 1, 4 significant below */
function ai365WgAmount(v) {
  var n = +v;
  if (!isFinite(n)) return '-';
  if (Math.abs(n) >= 100) return Math.round(n).toLocaleString('en-US');
  if (Math.abs(n) >= 1) return n.toLocaleString('en-US', { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
  return String(+n.toPrecision(4));
}

function ai365WgFxEl(card) {
  var lang = ai365WgLang();
  var el = document.createElement('div');
  el.className = 'ai365-wg ai365-wg-fx';
  el.setAttribute('data-wg', 'fx');
  var row = function (side) {
    var c = AI365_WG_CCY[side.code] || [side.code, side.code, side.code, ''];
    return '<div class="fx-row"><div class="fx-cur"><span class="fx-cc">' + ai365WgEsc(c[0]) + '</span>' + ai365WgEsc(lang === 'en' ? c[2] : c[1]) + '</div>'
      + '<div class="fx-amt">' + ai365WgEsc(c[3]) + ' ' + ai365WgAmount(side.amount) + '</div></div>';
  };
  var when = card.as_of ? (lang === 'en' ? ai365WgWhen(card.as_of, 'long') + ' KST' : ai365WgWhen(card.as_of, 'long') + ' KST ' + ai365WgT('asOf')) : '';
  el.innerHTML = row(card.base || {}) + row(card.quote || {})
    + '<div class="ai365-wg-foot"><a href="' + ai365WgUrl((card.source || {}).url) + '" target="_blank" rel="noopener">' + ai365WgEsc((card.source || {}).name || 'Yahoo Finance') + '</a>'
    + (when ? '<span>· ' + ai365WgEsc(when) + '</span>' : '') + '</div>';
  return el;
}

/* ───────────── 지도 / map ───────────── */
var AI365_WG_SVG = {
  star: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4L2.8 9.5l6.4-.8z"/></svg>',
  expand: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>',
  close: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  minus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14"/></svg>',
  reset: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l19-9-9 19-2-8z"/></svg>',
  clock: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  pin: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  phone: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
  chevron: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  img: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-8 9"/></svg>',
  map: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/></svg>'
};

function ai365WgRating(it) {
  return it.rating === null || it.rating === undefined ? '' : (+it.rating).toFixed(1);
}

function ai365WgMeta(it) {
  var r = ai365WgRating(it);
  return (r ? '★ ' + r : '') + (r && it.cat ? ' · ' : '') + (it.cat || '');
}

function ai365WgCardHtml(it, cls) {
  return '<button type="button" class="' + cls + '" data-pid="' + ai365WgEsc(it.id) + '">'
    + '<span class="ai365-wg-ph" data-photo="' + ai365WgEsc(it.id) + '">' + AI365_WG_SVG.img + '</span>'
    + '<span class="ai365-wg-tx"><span class="nm">' + ai365WgEsc(it.name) + '</span><span class="mt">' + ai365WgEsc(ai365WgMeta(it)) + '</span>'
    + (it.price ? '<span class="pr">' + ai365WgEsc(it.price) + '</span>' : '') + '</span></button>';
}

/* 사진 주소 — 같은 화면에서 한 번만 부른다(서버는 저장하지 않는다) / photo URI, fetched once per page (the server stores nothing) */
function ai365WgPhoto(it) {
  if (!it || !it.photo || !it.photo.name) return Promise.resolve(null);
  var key = it.photo.name;
  if (AI365_WG.photo[key] !== undefined) return Promise.resolve(AI365_WG.photo[key]);
  var p = ai365Fetch('/api/live/photo?w=480&name=' + encodeURIComponent(key))
    .then(function (d) { AI365_WG.photo[key] = (d && d.uri) || null; return AI365_WG.photo[key]; })
    .catch(function () { AI365_WG.photo[key] = null; return null; });
  AI365_WG.photo[key] = p;
  return p;
}

function ai365WgPaintPhoto(holder, it) {
  if (!holder || holder.getAttribute('data-done')) return;
  holder.setAttribute('data-done', '1');
  Promise.resolve(ai365WgPhoto(it)).then(function (uri) {
    if (!uri) return;
    holder.style.backgroundImage = 'url("' + String(uri).replace(/"/g, '%22') + '")';
    holder.innerHTML = '';
    if (it.photo && it.photo.author) holder.title = ai365WgT('photo') + ': ' + it.photo.author;
  });
}

/* 보이는 사진 칸만 부른다(무료 범위) / fetch only visible photo slots (free tier) */
function ai365WgLazyPhotos(root, items, scrollRoot) {
  var byId = {};
  (items || []).forEach(function (it) { byId[it.id] = it; });
  var slots = root.querySelectorAll('[data-photo]:not([data-done])');
  if (!('IntersectionObserver' in window)) {
    slots.forEach(function (s) { ai365WgPaintPhoto(s, byId[s.getAttribute('data-photo')]); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (!en.isIntersecting) return;
      io.unobserve(en.target);
      ai365WgPaintPhoto(en.target, byId[en.target.getAttribute('data-photo')]);
    });
  }, { root: scrollRoot || null, rootMargin: '40px' });
  slots.forEach(function (s) { io.observe(s); });
}

/* Maps JavaScript 를 한 번만 불러온다(언어는 처음 불러올 때의 화면 언어) / load Maps JavaScript once (language = UI language at first load) */
function ai365WgLoadMaps(key) {
  if (window.google && google.maps && google.maps.marker && google.maps.Map) return Promise.resolve(google.maps);
  if (AI365_WG.maps) return AI365_WG.maps;
  AI365_WG.maps = new Promise(function (resolve, reject) {
    window.__ai365MapsReady = function () { resolve(google.maps); };
    window.gm_authFailure = function () {
      AI365_WG.authFailed = true;
      document.querySelectorAll('.ai365-wg-pl[data-wg="places"]').forEach(function (el) { if (el.querySelector('.pl-map')) ai365WgNoMap(el, 'auth'); });
      var x = AI365_WG.mapx && AI365_WG.mapx.el;
      if (x && !x.querySelector('.mx-nomap')) { var n = document.createElement('div'); n.className = 'mx-nomap'; n.textContent = ai365WgMapNote('auth'); x.appendChild(n); }
    };
    var s = document.createElement('script');
    s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) + '&v=weekly&libraries=marker&loading=async'
      + '&callback=__ai365MapsReady&language=' + (ai365WgLang() === 'en' ? 'en' : 'ko') + '&region=KR';
    s.async = true;
    s.onerror = function () { AI365_WG.maps = null; reject(new Error('maps_load')); };
    document.head.appendChild(s);
  });
  return AI365_WG.maps;
}

function ai365WgPinEl(it) {
  var d = document.createElement('div');
  d.className = 'ai365-wg-pin';
  d.setAttribute('data-pid', it.id);
  var r = ai365WgRating(it);
  d.innerHTML = '<span class="b">' + (r ? AI365_WG_SVG.star + ' ' + r : AI365_WG_SVG.pin) + '</span><span class="n">' + ai365WgEsc(it.name) + '</span>';
  return d;
}

/* 지도 1개 만들기 — 먼저 서버에 지도 로드 허가(월 한도 +1)를 받는다 / make one map after the server grants a map load (monthly +1) */
function ai365WgMakeMap(el, items, opts) {
  opts = opts || {};
  // 키 인증이 이미 실패했으면 지도 로드를 세지 않는다 / after a key auth failure, do not count another map load
  if (AI365_WG.authFailed) { var e0 = new Error('auth'); e0.reason = 'auth'; return Promise.reject(e0); }
  return ai365Fetch('/api/live/map-load', { method: 'POST' }).then(function (p) {
    if (!p || !p.ok) { var e = new Error((p && p.reason) || 'no_map'); e.reason = (p && p.reason) || 'no_map'; throw e; }
    return ai365WgLoadMaps(p.key).then(function (gm) {
      if (AI365_WG.authFailed) { var e2 = new Error('auth'); e2.reason = 'auth'; throw e2; }
      var pts = (items || []).filter(function (it) { return it.lat !== null && it.lat !== undefined && it.lng !== null && it.lng !== undefined; });
      var center = pts.length ? { lat: +pts[0].lat, lng: +pts[0].lng } : { lat: 37.5665, lng: 126.978 };
      var map = new gm.Map(el, { center: center, zoom: 15, mapId: p.map_id, disableDefaultUI: true, clickableIcons: false,
                                 gestureHandling: opts.gesture || 'cooperative', keyboardShortcuts: !!opts.keyboard });
      var markers = {}, pins = {};
      pts.forEach(function (it) {
        var pin = ai365WgPinEl(it);
        var mk = new gm.marker.AdvancedMarkerElement({ map: map, position: { lat: +it.lat, lng: +it.lng }, content: pin, title: it.name });
        markers[it.id] = mk;
        pins[it.id] = pin;
        if (opts.onClick) {
          if ('gmpClickable' in mk) mk.addEventListener('gmp-click', function () { opts.onClick(it); });
          else mk.addListener('click', function () { opts.onClick(it); });
        }
        if (opts.onHover) {
          pin.addEventListener('mouseenter', function () { opts.onHover(it, pin, true); });
          pin.addEventListener('mouseleave', function () { opts.onHover(it, pin, false); });
        }
      });
      var fit = function () {
        if (pts.length > 1) {
          var b = new gm.LatLngBounds();
          pts.forEach(function (it) { b.extend({ lat: +it.lat, lng: +it.lng }); });
          map.fitBounds(b, opts.padding || 48);
        } else { map.setCenter(center); map.setZoom(16); }
      };
      fit();
      return { gm: gm, map: map, markers: markers, pins: pins, fit: fit, items: pts };
    });
  });
}

/* 지도 없이 카드 목록만(안내 한 줄) — 한 번만 / list-only fallback with one note line, applied once */
function ai365WgNoMap(el, reason) {
  if (el.classList.contains('no-map')) return;
  el.classList.add('no-map');
  var canvas = el.querySelector('.pl-canvas');
  if (canvas) canvas.innerHTML = '';
  var note = document.createElement('div');
  note.className = 'pl-note';
  note.textContent = ai365WgMapNote(reason);
  el.querySelector('.pl-map').insertBefore(note, el.querySelector('.pl-cards'));
}

function ai365WgMapNote(reason) {
  return ai365WgT(reason === 'quota' ? 'quota' : (reason === 'no_key' ? 'noKey' : 'noMap'));
}

function ai365WgPlacesEl(card) {
  var el = document.createElement('div');
  el.className = 'ai365-wg ai365-wg-pl';
  el.setAttribute('data-wg', 'places');
  var items = card.items || [];
  el.innerHTML = '<div class="pl-map"><div class="pl-canvas"></div>'
    + '<button type="button" class="pl-expand" data-expand>' + AI365_WG_SVG.expand + ' ' + ai365WgEsc(ai365WgT('expand')) + '</button>'
    + '<div class="pl-cards">' + items.map(function (it) { return ai365WgCardHtml(it, 'pl-card'); }).join('') + '</div></div>'
    + '<div class="ai365-wg-foot"><a href="' + ai365WgUrl((card.source || {}).url) + '" target="_blank" rel="noopener">' + ai365WgEsc((card.source || {}).name || ai365WgT('googleMaps')) + '</a></div>';
  var canvas = el.querySelector('.pl-canvas');
  var started = false;
  function start() {
    if (started) return;
    started = true;
    ai365WgLazyPhotos(el, items, el.querySelector('.pl-cards'));
    ai365WgMakeMap(canvas, items, { padding: { top: 56, right: 48, bottom: 130, left: 48 },
                                    onClick: function (it) { ai365WgOpenMapx(card, it.id); } })
      .catch(function (e) { ai365WgNoMap(el, e && e.reason); });
  }
  // 화면에 보일 때 지도를 만든다(지도 로드 절약) / create the map when visible (saves map loads)
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (en) { if (en.some(function (x) { return x.isIntersecting; })) { io.disconnect(); start(); } });
    setTimeout(function () { io.observe(el); }, 0);
  } else { setTimeout(start, 0); }
  el.addEventListener('click', function (e) {
    var b = e.target.closest('[data-expand],[data-pid]');
    if (!b || !el.contains(b)) return;
    ai365WgOpenMapx(card, b.hasAttribute('data-expand') ? null : b.getAttribute('data-pid'));
  });
  return el;
}

/* 복원 자리표시 — 구글 약관상 장소 데이터를 저장하지 않아 다시 불러온다 / restore placeholder: place data is not stored, so reload */
function ai365WgPlacesStaleEl(card) {
  var el = document.createElement('div');
  el.className = 'ai365-wg ai365-wg-pl';
  el.setAttribute('data-wg', 'places');
  el.innerHTML = '<div class="pl-stale"><span class="ic">' + AI365_WG_SVG.map + '</span><span class="tx"><b>'
    + ai365WgEsc(ai365WgT('staleTitle', { q: card.query || '', n: card.count || (card.ids || []).length || 0 })) + '</b><span>'
    + ai365WgEsc(ai365WgT('staleSub')) + '</span></span><button type="button" class="ai365-wg-btn" data-reload>' + ai365WgEsc(ai365WgT('reload')) + '</button></div>';
  el.querySelector('[data-reload]').addEventListener('click', function (e) {
    var btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = ai365WgT('loading');
    var q = encodeURIComponent(card.query || '');
    ai365Fetch('/api/live/places?q=' + q + '&lang=' + (card.lang === 'en' ? 'en' : 'ko') + '&area=' + encodeURIComponent(card.area || ''))
      .then(function (live) {
        var fresh = ai365WgPlacesEl(live);
        el.replaceWith(fresh);
      })
      .catch(function () { btn.disabled = false; btn.textContent = ai365WgT('reload'); if (typeof toast === 'function') toast(ai365WgT('failed')); });
  });
  return el;
}

/* 팝업 위치 — 기본은 핀 위, 위쪽이 24px 안이면 아래로, 좌우는 상자 안으로 / popup position: above the pin by default,
   below when it would sit within 24px of the top; kept inside the box horizontally */
function ai365WgPopPos(pin, pop, box) {
  var left = Math.max(8, Math.min(pin.left + pin.width / 2 - pop.w / 2, box.w - pop.w - 8));
  var top = pin.top - pop.h - 10;
  var below = false;
  if (top < 24) {
    var t2 = pin.top + pin.height + 10;
    if (t2 + pop.h <= box.h - 24) { top = t2; below = true; }
    else top = Math.max(24, top);
  }
  return { left: left, top: top, below: below };
}

/* ───────────── 크게 보기 / expanded view ───────────── */
function ai365WgOpenMapx(card, focusId) {
  ai365WgCloseMapx();
  var host = document.querySelector('.main') || document.body;
  var x = document.createElement('div');
  x.className = 'ai365-mapx';
  x.setAttribute('data-i18n-skip', '');
  x.innerHTML = '<div class="mx-map"></div>'
    + '<div class="mx-ctrl"><button type="button" class="mx-btn" data-x="close" title="' + ai365WgEsc(ai365WgT('close')) + '">' + AI365_WG_SVG.close + '</button>'
    + '<div class="mx-zoom"><button type="button" data-x="in" title="' + ai365WgEsc(ai365WgT('zoomIn')) + '">' + AI365_WG_SVG.plus + '</button>'
    + '<button type="button" data-x="out" title="' + ai365WgEsc(ai365WgT('zoomOut')) + '">' + AI365_WG_SVG.minus + '</button></div>'
    + '<button type="button" class="mx-btn" data-x="reset" title="' + ai365WgEsc(ai365WgT('reset')) + '">' + AI365_WG_SVG.reset + '</button></div>'
    + '<div class="mx-pop"></div><aside class="mx-side"></aside>';
  host.appendChild(x);
  var st = { card: card, items: (card.items || []).slice(), next: card.next || null, shown: 4, sel: null, view: 'list', m: null, hoverT: null };
  AI365_WG.mapx = { el: x, st: st };
  var side = x.querySelector('.mx-side'), pop = x.querySelector('.mx-pop');

  function listHtml() {
    var n = st.items.length, shown = Math.min(st.shown, n);
    var moreLbl = (shown < n || st.next) ? ai365WgT('more') : (n > 4 ? ai365WgT('less') : '');
    return '<div class="mx-head"><span>' + ai365WgEsc(ai365WgT('places', { n: n })) + '</span></div><div class="mx-body"><div class="mx-list">'
      + st.items.slice(0, shown).map(function (it) { return ai365WgCardHtml(it, 'mx-item' + (it.id === st.sel ? ' sel' : '')); }).join('')
      + '</div>' + (moreLbl ? '<button type="button" class="ai365-wg-btn mx-more" data-x="more">' + ai365WgEsc(moreLbl) + '</button>' : '') + '</div>';
  }
  function paintList() {
    st.view = 'list';
    side.innerHTML = listHtml();
    ai365WgLazyPhotos(side, st.items, side.querySelector('.mx-body'));
  }
  function selPin(id) {
    st.sel = id;
    if (!st.m) return;
    Object.keys(st.m.pins).forEach(function (k) { st.m.pins[k].classList.toggle('sel', k === id); });
  }
  function openDetail(id) {
    var it = st.items.filter(function (i) { return i.id === id; })[0];
    if (!it) return;
    selPin(id);
    hidePop();
    st.view = 'detail';
    side.innerHTML = '<div class="mx-head"><span>' + ai365WgEsc(ai365WgT('info')) + '</span><button type="button" data-x="back" title="' + ai365WgEsc(ai365WgT('back')) + '">' + AI365_WG_SVG.close + '</button></div>'
      + '<div class="mx-body"><div class="mx-dt">' + ai365WgDetailHtml(it, null) + '</div></div>';
    ai365WgDetailPhoto(side, it);
    if (st.m && it.lat !== null && it.lat !== undefined) st.m.map.panTo({ lat: +it.lat, lng: +it.lng });
    var cached = AI365_WG.detail[id];
    var load = cached ? Promise.resolve(cached) : ai365Fetch('/api/live/places/' + encodeURIComponent(id) + '?lang=' + (card.lang === 'en' ? 'en' : 'ko'))
      .then(function (d) { AI365_WG.detail[id] = d; return d; });
    load.then(function (d) {
      if (st.view !== 'detail' || st.sel !== id) return;
      side.querySelector('.mx-dt').innerHTML = ai365WgDetailHtml(it, d);
      ai365WgDetailPhoto(side, it);
    }).catch(function (e) {
      if (st.view !== 'detail' || st.sel !== id) return;
      var box = side.querySelector('.mx-more-info');
      if (box) box.innerHTML = '<p class="muted">' + ai365WgEsc(/429/.test(String(e && e.message)) ? ai365WgT('quotaDetail') : ai365WgT('failed')) + '</p>';
    });
  }
  function hidePop() { pop.classList.remove('on'); }
  function showPop(it, pinEl) {
    clearTimeout(st.hoverT);
    pop.innerHTML = '<div class="row">' + '<span class="ai365-wg-ph" data-photo="' + ai365WgEsc(it.id) + '">' + AI365_WG_SVG.img + '</span>'
      + '<span class="ai365-wg-tx"><span class="nm">' + ai365WgEsc(it.name) + '</span><span class="mt">' + ai365WgEsc(ai365WgMeta(it)) + '</span>'
      + (it.price ? '<span class="pr">' + ai365WgEsc(it.price) + '</span>' : '') + '</span></div>'
      + '<div class="acts">' + (it.dir ? '<a class="ai365-wg-btn" href="' + ai365WgUrl(it.dir) + '" target="_blank" rel="noopener">' + ai365WgEsc(ai365WgT('route')) + '</a>' : '')
      + (it.phone ? '<a class="ai365-wg-btn" href="tel:' + ai365WgEsc(it.phone.replace(/[^0-9+]/g, '')) + '" title="' + ai365WgEsc(it.phone) + '">' + ai365WgEsc(ai365WgT('call')) + '</a>' : '') + '</div>';
    pop.setAttribute('data-pid', it.id);
    pop.classList.add('on');
    ai365WgPaintPhoto(pop.querySelector('[data-photo]'), it);
    var box = x.getBoundingClientRect(), r = pinEl.getBoundingClientRect();
    var pos = ai365WgPopPos({ left: r.left - box.left, top: r.top - box.top, width: r.width, height: r.height },
                            { w: pop.offsetWidth || 260, h: pop.offsetHeight || 120 }, { w: box.width, h: box.height });
    pop.style.left = pos.left + 'px';
    pop.style.top = pos.top + 'px';
  }
  pop.addEventListener('mouseenter', function () { clearTimeout(st.hoverT); });
  pop.addEventListener('mouseleave', function () { st.hoverT = setTimeout(hidePop, 180); });
  pop.addEventListener('click', function (e) {
    if (e.target.closest('a')) return;
    var id = pop.getAttribute('data-pid');
    if (id) openDetail(id);
  });

  function onKey(e) {
    if (e.key !== 'Escape' || !AI365_WG.mapx || AI365_WG.mapx.el !== x) return;
    e.stopPropagation();
    if (st.view === 'detail') { paintList(); selPin(null); } else ai365WgCloseMapx();
  }
  document.addEventListener('keydown', onKey, true);
  AI365_WG.mapx.off = function () { document.removeEventListener('keydown', onKey, true); };

  x.addEventListener('click', function (e) {
    var b = e.target.closest('[data-x],[data-pid],[data-copy-text]');
    if (!b || !x.contains(b) || b === pop || pop.contains(b)) return;
    var act = b.getAttribute('data-x');
    if (act === 'close') return ai365WgCloseMapx();
    if (act === 'in' && st.m) return st.m.map.setZoom((st.m.map.getZoom() || 15) + 1);
    if (act === 'out' && st.m) return st.m.map.setZoom((st.m.map.getZoom() || 15) - 1);
    if (act === 'reset' && st.m) return st.m.fit();
    if (act === 'back') { paintList(); selPin(null); return; }
    if (act === 'hours') { var hb = side.querySelector('.hours'); if (hb) hb.hidden = !hb.hidden; return; }
    if (act === 'more') {
      var n = st.items.length;
      if (st.shown < n) { st.shown = n; paintList(); return; }
      if (st.next) {
        b.disabled = true;
        b.textContent = ai365WgT('loading');
        ai365Fetch('/api/live/places?q=' + encodeURIComponent(card.query || '') + '&lang=' + (card.lang === 'en' ? 'en' : 'ko') + '&page=' + encodeURIComponent(st.next))
          .then(function (res) {
            var known = {};
            st.items.forEach(function (i) { known[i.id] = 1; });
            var add = (res.items || []).filter(function (i) { return !known[i.id]; });
            st.items = st.items.concat(add);
            st.next = res.next || null;
            st.shown = st.items.length;
            if (st.m) ai365WgAddMarkers(st, add, openDetail, onHover);
            paintList();
          })
          .catch(function () { if (typeof toast === 'function') toast(ai365WgT('failed')); paintList(); });
        return;
      }
      st.shown = 4;
      paintList();
      return;
    }
    if (b.hasAttribute('data-copy-text')) {
      var txt = b.getAttribute('data-copy-text');
      if (navigator.clipboard) navigator.clipboard.writeText(txt).then(function () { if (typeof toast === 'function') toast(ai365WgT('copied')); }, function () {});
      return;
    }
    var pid = b.getAttribute('data-pid');
    if (pid && b.classList.contains('mx-item')) openDetail(pid);
  });

  function onHover(it, pinEl, on) {
    if (on) showPop(it, pinEl);
    else { clearTimeout(st.hoverT); st.hoverT = setTimeout(hidePop, 180); }
  }

  paintList();
  if (focusId) openDetail(focusId);
  ai365WgMakeMap(x.querySelector('.mx-map'), st.items, {
    gesture: 'greedy', keyboard: true, padding: { top: 72, right: 448, bottom: 48, left: 88 },
    onClick: function (it) { openDetail(it.id); }, onHover: onHover
  }).then(function (m) {
    if (!AI365_WG.mapx || AI365_WG.mapx.el !== x) return;
    st.m = m;
    if (st.sel) selPin(st.sel);
  }).catch(function (e) {
    var note = document.createElement('div');
    note.className = 'mx-nomap';
    note.textContent = ai365WgMapNote(e && e.reason);
    x.appendChild(note);
  });
}

function ai365WgAddMarkers(st, items, openDetail, onHover) {
  var gm = st.m.gm;
  items.forEach(function (it) {
    if (it.lat === null || it.lat === undefined) return;
    var pin = ai365WgPinEl(it);
    var mk = new gm.marker.AdvancedMarkerElement({ map: st.m.map, position: { lat: +it.lat, lng: +it.lng }, content: pin, title: it.name });
    if ('gmpClickable' in mk) mk.addEventListener('gmp-click', function () { openDetail(it.id); });
    else mk.addListener('click', function () { openDetail(it.id); });
    pin.addEventListener('mouseenter', function () { onHover(it, pin, true); });
    pin.addEventListener('mouseleave', function () { onHover(it, pin, false); });
    st.m.markers[it.id] = mk;
    st.m.pins[it.id] = pin;
    st.m.items.push(it);
  });
}

function ai365WgDetailPhoto(side, it) {
  var hero = side.querySelector('.mx-hero');
  if (!hero || !it.photo) return;
  Promise.resolve(ai365WgPhoto(it)).then(function (uri) {
    if (uri) hero.style.backgroundImage = 'url("' + String(uri).replace(/"/g, '%22') + '")';
  });
}

/* 가게 정보 패널 본문 — d 가 없으면 목록 값만(가게 정보를 불러오는 중) / the place-detail body; list values only until d arrives */
function ai365WgDetailHtml(it, d) {
  var lang = ai365WgLang();
  var p = d || it;
  var credit = it.photo && it.photo.author
    ? '<span class="credit">' + ai365WgEsc(ai365WgT('photo')) + ': ' + (it.photo.author_uri ? '<a href="' + ai365WgUrl(it.photo.author_uri) + '" target="_blank" rel="noopener">' + ai365WgEsc(it.photo.author) + '</a>' : ai365WgEsc(it.photo.author)) + '</span>'
    : '';
  var acts = '<div class="acts">'
    + (p.dir ? '<a class="ai365-wg-btn pri" href="' + ai365WgUrl(p.dir) + '" target="_blank" rel="noopener">' + ai365WgEsc(ai365WgT('route')) + '</a>' : '')
    + (p.web ? '<a class="ai365-wg-btn" href="' + ai365WgUrl(p.web) + '" target="_blank" rel="noopener">' + ai365WgEsc(ai365WgT('web')) + '</a>' : '')
    + (p.phone ? '<a class="ai365-wg-btn" href="tel:' + ai365WgEsc(p.phone.replace(/[^0-9+]/g, '')) + '" title="' + ai365WgEsc(p.phone) + '">' + ai365WgEsc(ai365WgT('call')) + '</a>' : '')
    + '</div>';
  var open = p.open ? '<div class="line">' + AI365_WG_SVG.clock + '<div class="grow">'
      + (d && d.hours && d.hours.length
        ? '<button type="button" class="hours-btn" data-x="hours"><span>' + ai365WgEsc(p.open.label) + '</span>' + AI365_WG_SVG.chevron + '</button>'
          + '<div class="hours" hidden>' + d.hours.map(function (h) { return '<span>' + ai365WgEsc(h.day) + '</span><span>' + ai365WgEsc(h.time) + '</span>'; }).join('') + '</div>'
        : '<span>' + ai365WgEsc(p.open.label) + '</span>')
      + '</div></div>' : '';
  var addr = (d && d.addr_full) || it.addr;
  var lines = open
    + (addr ? '<div class="line">' + AI365_WG_SVG.pin + '<div class="grow copyable"><span class="tx">' + ai365WgEsc(addr) + '</span><button type="button" class="copy-ic" data-copy-text="' + ai365WgEsc(addr) + '" title="' + ai365WgEsc(ai365WgT('copy')) + '">' + AI365_WG_SVG.copy + '</button></div></div>' : '')
    + (p.phone ? '<div class="line">' + AI365_WG_SVG.phone + '<div class="grow">' + ai365WgEsc(p.phone) + '</div></div>' : '');
  var more = '';
  if (!d) {
    more = '<div class="mx-more-info"><p class="muted">' + ai365WgEsc(ai365WgT('loading')) + '</p></div>';
  } else {
    more = (d.about ? '<p class="about">' + ai365WgEsc(d.about) + '</p>' : '')
      + '<h4>' + ai365WgEsc(ai365WgT('reviews')) + '</h4>'
      + ((d.reviews || []).length ? d.reviews.map(function (r) {
        var who = r.author_uri ? '<a href="' + ai365WgUrl(r.author_uri) + '" target="_blank" rel="noopener">' + ai365WgEsc(r.author) + '</a>' : '<b>' + ai365WgEsc(r.author) + '</b>';
        return '<div class="rv"><div class="rv-h">' + (r.avatar ? '<img src="' + ai365WgUrl(r.avatar) + '" alt="" referrerpolicy="no-referrer">' : '') + who
          + (r.rating ? '<span>★ ' + ai365WgEsc(r.rating) + '</span>' : '') + (r.when ? '<span>· ' + ai365WgEsc(r.when) + '</span>' : '') + '</div>'
          + '<div class="rv-t">' + ai365WgEsc(r.text) + '</div>'
          + (r.uri ? '<a class="rv-more" href="' + ai365WgUrl(r.uri) + '" target="_blank" rel="noopener">' + ai365WgEsc(ai365WgT('more1')) + '</a>' : '') + '</div>';
      }).join('') : '<p class="muted">' + ai365WgEsc(ai365WgT('noReviews')) + '</p>')
      + (d.reviews_uri ? '<a class="rv-more" href="' + ai365WgUrl(d.reviews_uri) + '" target="_blank" rel="noopener">' + ai365WgEsc(ai365WgT('moreReviews')) + '</a>' : '');
  }
  var copyAll = [p.name || it.name, addr, p.phone].filter(Boolean).join('\n');
  return '<div class="mx-hero">' + credit + '</div>'
    + '<h3>' + ai365WgEsc(p.name || it.name) + '</h3><div class="meta">' + ai365WgEsc(ai365WgMeta(p.rating !== undefined ? p : it)) + '</div>'
    + acts + lines + more
    + '<div class="foot"><button type="button" data-copy-text="' + ai365WgEsc(copyAll) + '" title="' + ai365WgEsc(ai365WgT('copy')) + '">' + AI365_WG_SVG.copy + '</button></div>';
}

function ai365WgCloseMapx() {
  var cur = AI365_WG.mapx;
  if (!cur) return;
  AI365_WG.mapx = null;
  if (cur.off) cur.off();
  if (cur.el && cur.el.parentNode) cur.el.parentNode.removeChild(cur.el);
}

/* 다른 화면으로 가면 크게 보기를 닫는다 / close the expanded view on any navigation */
(function () {
  if (typeof window.showView !== 'function' || window.showView.__ai365Wg) return;
  var prev = window.showView;
  var wrapped = function () { ai365WgCloseMapx(); return prev.apply(this, arguments); };
  wrapped.__ai365Wg = true;
  window.showView = wrapped;
})();
