/* Shared by puzzle.html and puzzle-staff.html [badmintonGPT fork]: the survey questions and the
   bootstrap-token GET client. Survey names/values must match nanobot/puzzle.py SURVEY_RATINGS /
   SURVEY_CHOICES. */
(function () {
  // Every 1–5 scale names each point, not just the two ends.
  // "|" marks where a caption may wrap on a narrow phone.
  var AGREE = ["非常|不同意", "不同意", "普通", "同意", "非常|同意"];
  var QUESTIONS = [
    { name: "fit", type: "scale", labels: AGREE, short: "解謎時回答符合需求",
      label: "解謎時，BadmintonGPT 的回答符合你的需求" },
    { name: "tried_other", type: "choice", label: "除了解謎，你有沒有自己問 BadmintonGPT 其他問題？",
      options: [["yes", "有"], ["no", "沒有"]] },
    { name: "other_fit", type: "scale", labels: AGREE, when: ["tried_other", "yes"], short: "其他問題回答符合需求",
      label: "你自己問的那些問題，BadmintonGPT 的回答符合你的需求" },
    { name: "overall", type: "scale", labels: ["非常|不滿意", "不滿意", "普通", "滿意", "非常|滿意"],
      short: "整體滿意度", label: "整體來說，你對 BadmintonGPT 的滿意度" },
    { name: "recommend", type: "scale", labels: ["非常|不可能", "不太|可能", "普通", "可能", "非常|可能"],
      short: "推薦給球友或隊友", label: "你有多大可能把 BadmintonGPT 推薦給球友或隊友？" },
    { name: "role", type: "choice", label: "你的身份",
      options: [["player", "選手"], ["coach", "教練"], ["amateur", "業餘羽球愛好者"], ["fan", "球迷"],
                ["research", "研究人員"], ["public", "一般民眾"], ["other", "其他"]] },
    { name: "level", type: "choice", label: "你的羽球程度",
      options: [["none", "幾乎不打"], ["casual", "偶爾休閒打"], ["regular", "固定打球（社團、系隊）"],
                ["competitive", "校隊或以上"]] },
    { name: "suggestion", type: "text", optional: true, max: 500,
      label: "有什麼建議，或希望 BadmintonGPT 增加什麼功能？" },
  ];

  var token = null;
  var account = null;

  function bootstrap() {
    return fetch("/webui/bootstrap", { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error(r.status === 401 || r.status === 403 ? "auth" : "boot");
      return r.json();
    }).then(function (b) {
      token = b.token;
      account = b.account || account;
    });
  }

  // GET with the bootstrap token; re-bootstrap once if it expired (TTL is a few minutes).
  function api(path, retried) {
    var go = token ? Promise.resolve() : bootstrap();
    return go.then(function () {
      return fetch(path, {
        credentials: "same-origin",
        headers: { Authorization: "Bearer " + token },
      });
    }).then(function (r) {
      if (r.status === 401 && !retried) { token = null; return api(path, true); }
      return r;
    });
  }

  function timestamp(d) {
    var p = function (x) { return (x < 10 ? "0" : "") + x; };
    return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " +
      p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  window.Puzzle = {
    QUESTIONS: QUESTIONS,
    api: api,
    email: function () { return account && account.email; },
    timestamp: timestamp,
    // What the done screen's QR encodes; puzzle-staff.html reads the code from the hash.
    stampUrl: function (code) { return location.origin + "/puzzle-staff.html#c=" + encodeURIComponent(code); },
  };
})();
