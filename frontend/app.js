/* 主应用 */
(function () {
  if (!window.Vue) {
    document.getElementById("app").innerHTML =
      '<div style="padding:40px;font-family:sans-serif">Vue 未加载成功。请检查 frontend/vendor/vue.global.prod.js 是否存在，或在有网络的环境下运行。</div>';
    return;
  }

  const { createApp } = window.Vue;
  const { Icon, Chart, Stat, Empty, Loading } = window.Components;
  const V = window.Views;

  const NAV = [
    { group: "服务", items: [
      { key: "chat", label: "知识问答", icon: "chat", comp: "ChatView" },
      { key: "recommend", label: "竞赛推荐", icon: "spark", comp: "RecommendView" },
      { key: "prep", label: "备赛辅助", icon: "calendar", comp: "PrepView" },
      { key: "review", label: "材料评审", icon: "file", comp: "ReviewView" },
    ]},
    { group: "数据", items: [
      { key: "stats", label: "数据统计", icon: "chart", comp: "StatsView" },
      { key: "finance", label: "经费辅助", icon: "wallet", comp: "FinanceView" },
    ]},
    { group: "管理", items: [
      { key: "knowledge", label: "知识库", icon: "book", comp: "KnowledgeView" },
      { key: "system", label: "系统状态", icon: "gear", comp: "SystemView" },
    ]},
  ];

  const ALL_KEYS = NAV.flatMap((g) => g.items.map((i) => i.key));

  function fromHash() {
    const h = (location.hash || "").replace(/^#\/?/, "");
    return ALL_KEYS.includes(h) ? h : "chat";
  }

  const app = createApp({
    components: { Icon, Chart, Stat, Empty, Loading },
    data() {
      return {
        nav: NAV,
        active: fromHash(),
        health: null,
      };
    },
    computed: {
      currentComp() {
        for (const g of this.nav) {
          const hit = g.items.find((i) => i.key === this.active);
          if (hit) return V[hit.comp];
        }
        return V.ChatView;
      },
      llmText() {
        if (!this.health) return "连接中…";
        const l = this.health.llm;
        if (l.available) return `${l.provider} · ${l.model}`;
        return "未接入大模型";
      },
      llmOk() {
        return !!(this.health && this.health.llm && this.health.llm.available);
      },
    },
    mounted() {
      this.check();
      // 刷新保持当前页，也便于把某一页作为链接分享出去
      window.addEventListener("hashchange", () => {
        const k = fromHash();
        if (k !== this.active) this.active = k;
      });
    },
    watch: {
      active(k) {
        if (fromHash() !== k) location.hash = k;
      },
    },
    methods: {
      go(key) {
        this.active = key;
      },
      async check() {
        try {
          this.health = await API.health();
        } catch (e) {
          this.health = { llm: { available: false, provider: "—", model: "服务未就绪" } };
        }
      },
    },
    template: `
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">
          <h1>竞赛辅助服务</h1>
          <p>计算与智能技术学院</p>
        </div>
        <nav class="nav">
          <template v-for="g in nav" :key="g.group">
            <div class="nav-group">{{ g.group }}</div>
            <button v-for="it in g.items" :key="it.key"
                    class="nav-item" :class="{active: active === it.key}"
                    @click="go(it.key)">
              <icon :name="it.icon" :size="16" />
              <span>{{ it.label }}</span>
            </button>
          </template>
        </nav>
        <div class="sidebar-foot">
          <div><span class="dot" :class="llmOk ? 'ok' : 'warn'"></span>{{ llmText }}</div>
          <div style="margin-top:2px">v1.0.0</div>
        </div>
      </aside>

      <main class="main">
        <component :is="currentComp" :key="active" />
      </main>
    </div>`,
  });

  // 全局注册基础组件。只写在根实例的 components 里是不够的——
  // 子视图（StatsView 等）自己解析 <chart> <stat> <icon> 时会当成未知标签，
  // 页面上就会出现 option="[object Object]" 这种空壳节点。
  Object.keys(window.Components || {}).forEach((name) => {
    if (name !== "renderMarkdown") app.component(name, window.Components[name]);
  });

  app.mount("#app");
})();