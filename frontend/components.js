/* 通用组件与工具 */
(function () {
  const ICONS = {
    chat: "M4 5.5h16v10H8.5L4 19V5.5z",
    book: "M4 4.5h6.5a2 2 0 012 2V20a2 2 0 00-2-2H4V4.5zm16 0h-6.5a2 2 0 00-2 2V20a2 2 0 012-2H20V4.5z",
    spark: "M12 3l1.9 4.9L19 9.8l-4 3.6.9 5.1L12 16.1 8.1 18.5l.9-5.1-4-3.6 5.1-1.9L12 3z",
    calendar: "M4 7h16v13H4V7zm3-3v3m10-3v3M4 11h16",
    file: "M6 3h8l4 4v14H6V3zm8 0v4h4",
    chart: "M4 20V10m5 10V5m5 15v-7m5 7V8",
    wallet: "M3 7h18v12H3V7zm0 3h18M16 13h2",
    gear: "M12 8.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7zM12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4",
    upload: "M12 16V4m0 0l-4 4m4-4l4 4M4 16v4h16v-4",
    download: "M12 4v12m0 0l4-4m-4 4l-4-4M4 20h16",
    plus: "M12 5v14M5 12h14",
    trash: "M4 7h16M9 7V4h6v3m-8 0l1 13h8l1-13",
    send: "M4 12l16-8-6 16-2.5-6.5L4 12z",
    search: "M11 4a7 7 0 100 14 7 7 0 000-14zm5.5 12.5L21 21",
    refresh: "M20 12a8 8 0 11-2.3-5.6M20 4v4h-4",
    check: "M4 12.5l5 5L20 6",
    close: "M6 6l12 12M18 6L6 18",
    doc: "M7 3h7l4 4v14H7V3zm7 0v4h4M9 13h6M9 17h4",
    users: "M8 11a3 3 0 100-6 3 3 0 000 6zm8 0a3 3 0 100-6 3 3 0 000 6zM2 20c0-3 2.7-5 6-5s6 2 6 5m2-5c3 0 6 2 6 5",
  };

  const Icon = {
    props: { name: { type: String, required: true }, size: { type: [Number, String], default: 16 } },
    computed: {
      path() {
        return ICONS[this.name] || ICONS.doc;
      },
    },
    template: `<svg :width="size" :height="size" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path :d="path" /></svg>`,
  };

  /* ---------------------------------------------------------- Markdown */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function inline(s) {
    return esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, '<code style="background:#f5f5f7;padding:1px 5px;border-radius:4px;font-size:12.5px">$1</code>');
  }

  function renderMarkdown(text) {
    if (!text) return "";
    const lines = String(text).split("\n");
    const out = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      // 表格
      if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|[\s\-:|]+\|/.test(lines[i + 1])) {
        const head = line.split("|").slice(1, -1).map((c) => c.trim());
        i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) {
          rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
          i++;
        }
        out.push(
          "<table><thead><tr>" +
            head.map((h) => "<th>" + inline(h) + "</th>").join("") +
            "</tr></thead><tbody>" +
            rows.map((r) => "<tr>" + r.map((c) => "<td>" + inline(c) + "</td>").join("") + "</tr>").join("") +
            "</tbody></table>"
        );
        continue;
      }

      if (/^###\s+/.test(line)) {
        out.push("<h3>" + inline(line.replace(/^###\s+/, "")) + "</h3>");
        i++;
        continue;
      }
      if (/^##\s+/.test(line)) {
        out.push("<h2>" + inline(line.replace(/^##\s+/, "")) + "</h2>");
        i++;
        continue;
      }
      if (/^>\s?/.test(line)) {
        const buf = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          buf.push(lines[i].replace(/^>\s?/, ""));
          i++;
        }
        out.push("<blockquote>" + inline(buf.join(" ")) + "</blockquote>");
        continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
          buf.push("<li>" + inline(lines[i].replace(/^\s*[-*]\s+/, "").replace(/^\[ \]\s*/, "☐ ")) + "</li>");
          i++;
        }
        out.push("<ul>" + buf.join("") + "</ul>");
        continue;
      }
      if (/^\s*\d+\.\s+/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          buf.push("<li>" + inline(lines[i].replace(/^\s*\d+\.\s+/, "")) + "</li>");
          i++;
        }
        out.push("<ol style='padding-left:20px;list-style:decimal'>" + buf.join("") + "</ol>");
        continue;
      }
      if (line.trim() === "") {
        i++;
        continue;
      }
      out.push("<p>" + inline(line) + "</p>");
      i++;
    }
    return out.join("");
  }

  /* ---------------------------------------------------------- 图表 */
  const Chart = {
    props: { option: { type: Object, default: () => ({}) }, height: { type: String, default: "280px" } },
    template: `<div ref="el" :style="{width:'100%',height:height}"></div>`,
    mounted() {
      this.draw();
      this._ro = new ResizeObserver(() => this.chart && this.chart.resize());
      if (this.$refs.el) this._ro.observe(this.$refs.el);
    },
    beforeUnmount() {
      if (this._ro) this._ro.disconnect();
      if (this.chart) this.chart.dispose();
    },
    watch: {
      option: { deep: true, handler() { this.draw(); } },
    },
    methods: {
      draw() {
        if (!window.echarts || !this.$refs.el) return;
        if (!this.chart) this.chart = window.echarts.init(this.$refs.el, null, { renderer: "svg" });
        this.chart.setOption(
          Object.assign(
            {
              textStyle: { fontFamily: "-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif" },
              grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
              tooltip: { trigger: "axis" },
            },
            this.option
          ),
          true
        );
      },
    },
  };

  const Stat = {
    props: ["label", "value", "unit", "sub"],
    template: `<div class="stat">
      <div class="label">{{ label }}</div>
      <div class="value">{{ value }}<span class="unit" v-if="unit">{{ unit }}</span></div>
      <div class="sub" v-if="sub">{{ sub }}</div>
    </div>`,
  };

  const Empty = {
    props: { text: { type: String, default: "暂无数据" } },
    template: `<div class="empty">{{ text }}</div>`,
  };

  const Loading = {
    props: { text: { type: String, default: "处理中" } },
    template: `<div class="empty"><span class="spinner"></span><span style="margin-left:10px">{{ text }}</span></div>`,
  };

  window.Components = { Icon, Chart, Stat, Empty, Loading, renderMarkdown };
})();
