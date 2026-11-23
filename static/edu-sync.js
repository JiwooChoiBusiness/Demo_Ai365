/* 교육 SPA 서버 동기화(2026-08-24 실구축 1차, 최소 범위) — GET /edu가 응답 시점에 주입한다
   (바탕화면 원본·저장소 스냅숏 모두 무수정 — GET / 의 adapter.js 주입 관례).
   ① 부팅 동기화: 실 스토어(GET /api/edu/documents·/audit)의 상태를 제목 매칭으로 SPA in-page DB에
      입혀 서버에서 일어난 판정(승인·반려·재큐)이 화면에도 보이게 한다. 매칭 안 되는 문서는 건드리지
      않는다(SPA 자체 시드 유지).
   ② 변이 미러: SPA의 전역 transition()을 래핑해 사람 판정(승인·반려)·재큐를 해당 서버 API로
      fire-and-forget 미러 — 화면에서 한 판정이 채팅·API 답변에도 반영된다. SPA 렌더 로직은 무수정.
   서버 미가용 시 조용히 포기(시연 내성). */
/* Edu-SPA server sync (minimal scope) — injected at serve time by GET /edu (neither the Desktop
   original nor the repo snapshot is edited). Boot sync overlays real-store states onto the in-page
   DB by title match; a wrapped global transition() mirrors human verdicts/requeues to the server
   APIs fire-and-forget. Silently gives up when the server is unreachable. */
(async function () {
  try {
    if (typeof DB === 'undefined' || !DB.docs || !DB.docs.length) return;
    // 뷰애즈 신원 — 임베드 iframe URL의 acting_user_id를 조회·미러 전부에 동봉(무지정=슈퍼, 리뷰 확정)
    // View-as identity — forwarded to every read and mirror call (absent = super; review finding)
    const AID = new URLSearchParams(location.search).get('acting_user_id') || '';
    const j = async function (u) {
      const r = await fetch(u + (u.indexOf('?') >= 0 ? '&' : '?') + (AID ? 'acting_user_id=' + encodeURIComponent(AID) : ''));
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return (await r.json()).data;
    };
    const docs = (await j('/api/edu/documents')).documents;
    const byTitle = {};
    docs.forEach(function (d) { byTitle[d.title] = d; });
    DB.docs.forEach(function (d) {
      const s = byTitle[d.title];
      if (!s || !s.state) return;
      d.state = s.state;
      d.appliedLic = s.applied_lic || null;
      if (s.eval_why) d.evalWhy = s.eval_why;
      if (s.rules && s.rules.length) d.rules = s.rules;
      if (s.sp_name) { d.spName = s.sp_name; d.uploadedAt = s.uploaded_at || d.uploadedAt; }
      if (d.state !== 'staged') { d.stagedUntil = null; }
    });
    try {
      const audit = (await j('/api/edu/audit?top=50')).events;
      if (audit && audit.length) {
        DB.audit = audit.map(function (e) {
          return { t: (e.t || '').slice(11, 16) || e.t, doc: e.doc, move: e.move, by: e.by, note: e.note || '' };
        });
      }
    } catch (e) { /* 감사 로그만 실패해도 문서 동기화는 유지 / audit failure keeps the doc overlay */ }
    if (typeof render === 'function') render();

    if (typeof transition === 'function') {
      const orig = transition;
      transition = function (d, to, by, note) {
        orig(d, to, by, note);
        const s = byTitle[d.title];
        if (!s) return;
        const H = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
        const P = function (o) { o.acting_user_id = AID; return JSON.stringify(o); };
        try {
          if (to === 'uploaded' && (s.state === 'review' || s.state === 'staged')) {
            // staged→uploaded(유예 만료·수동 확정)도 미러 — 서버 submit_review가 staged 승인을 허용(리뷰 확정)
            // staged→uploaded (grace expiry / manual confirm) mirrors too — the server accepts staged approvals
            s.state = 'uploaded';
            fetch('/api/edu/documents/' + encodeURIComponent(s.id) + '/review',
              Object.assign({}, H, { body: P({ verdict: 'approve', note: note || '화면 판정 미러' }) }));
          } else if (to === 'rejected' && s.state === 'review') {
            s.state = 'rejected';
            fetch('/api/edu/documents/' + encodeURIComponent(s.id) + '/review',
              Object.assign({}, H, { body: P({ verdict: 'reject', note: note || '화면 판정 미러' }) }));
          } else if (to === 'review' && (s.state === 'held' || s.state === 'rejected')) {
            s.state = 'review';
            fetch('/api/edu/pipeline/requeue',
              Object.assign({}, H, { body: P({ documentId: s.id }) }));
          }
        } catch (e) { /* 미러 실패는 화면 동작에 영향 없음 / mirror failures never affect the page */ }
      };
    }
  } catch (e) { /* 서버 미가용 — SPA 자체 시드 유지 / server unavailable: the SPA's own seeds remain */ }
})();
