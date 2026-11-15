/* 页面：材料评审 / 数据统计 / 经费 / 系统 */
(function () {
  const { renderMarkdown } = window.Components;

  /* ================================================================ 材料评审 */
  const ReviewView = {
    data() {
      return {
        competitions: [],
        competition: "",
        content: "",
        filename: "",
        loading: false,
        result: null,
        err: "",
      };
    },
    computed: {
      chars() {
        return this.content.length;
      },
    },
    mounted() {
      API.competitions({}).then((r) => {
        this.competitions = r.items;
      }).catch(() => {});
    },
    methods: {
      async onFile(e) {
        const f = e.target.files[0];
        if (!f) return;
        this.filename = f.name;
        if (f.name.endsWith(".txt") || f.name.endsWith(".md")) {
          this.content = await f.text();
        } else {
          this.err = "浏览器端仅读取纯文本。Word 文件请直接用下方接口上传，或把正文粘贴到文本框。";
        }
        e.target.value = "";
      },
      async uploadDocx(e) {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData();
        fd.append("files", f);
        try {
          await API.upload("/api/knowledge/upload", fd);
          this.err = "文件已上传到知识库，但材料评审请把正文粘贴到文本框（或使用 API 的 file_path 参数）。";
        } catch (err) {
          this.err = err.message;
        }
        e.target.value = "";
      },
      async run() {
        if (!this.content.trim()) {
          this.err = "请粘贴材料正文";
          return;
        }
        this.loading = true;
        this.err = "";
        this.result = null;
        try {
          this.result = await API.runWorkflow("review", {
            content: this.content,
            filename: this.filename,
            competition: this.competition,
          });
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      sevClass(s) {
        return { 高: "tag-danger", 中: "tag-warn", 低: "tag" }[s] || "tag";
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>项目材料评审</h2>
        <p>对申报书、作品说明做初步检查：完整性、规范性、创新点、可行性与表达问题，并预判答辩提问。给出的是可执行的修改建议，不是泛泛评价。</p>
      </div>

      <div class="card">
        <div class="grid grid-3" style="align-items:end">
          <div class="field" style="grid-column: span 2">
            <label>参赛赛事（可选，用于匹配评审标准）</label>
            <select class="select" v-model="competition">
              <option value="">不指定</option>
              <option v-for="c in competitions" :key="c.code" :value="c.name">{{ c.name }}</option>
            </select>
          </div>
          <div class="field">
            <label>读取本地文本</label>
            <input type="file" class="input" accept=".txt,.md" @change="onFile" />
          </div>
        </div>

        <div class="field mt-16">
          <label>材料正文 <span class="tiny">（当前 {{ chars }} 字，建议 1500 字以上）</span></label>
          <textarea class="textarea" v-model="content" style="min-height:260px"
            placeholder="把申报书或作品说明的正文粘贴到这里…"></textarea>
        </div>

        <div class="row mt-16">
          <button class="btn btn-primary" :disabled="loading || !content.trim()" @click="run">
            {{ loading ? '评审中…' : '开始评审' }}
          </button>
          <button class="btn" @click="content = demoText()">填入示例材料</button>
          <span class="tiny" style="align-self:center">示例材料故意写得有缺陷，用于演示问题检出</span>
        </div>
      </div>

      <div v-if="err" class="alert alert-err mt-16">{{ err }}</div>
      <div v-if="loading" class="card mt-16"><div class="empty"><span class="spinner"></span> 正在比对评审要点</div></div>

      <div v-if="result" class="mt-16">
        <div class="grid grid-4">
          <stat label="初评得分" :value="result.data.review.score" unit="分" />
          <stat label="材料字数" :value="result.data.char_count" unit="字" />
          <stat label="检出问题" :value="result.data.review.issues.length" unit="项" />
          <stat label="答辩预判" :value="result.data.review.defense_questions.length" unit="题" />
        </div>

        <div class="card mt-16">
          <div class="card-title">分维度评价</div>
          <div v-for="d in result.data.review.dimensions" :key="d.name" class="list-item">
            <span style="width:110px;font-size:13px">{{ d.name }}</span>
            <div style="flex:1;height:5px;background:var(--bg-sub);border-radius:3px;overflow:hidden">
              <div :style="{width: d.score + '%', height:'100%', background: d.score>=80 ? 'var(--ok)' : (d.score>=60 ? 'var(--accent)' : 'var(--warn)')}"></div>
            </div>
            <span class="mono" style="width:34px;text-align:right;font-size:13px">{{ d.score }}</span>
            <span class="tiny" style="width:180px">{{ d.comment }}</span>
          </div>
        </div>

        <div class="card mt-16">
          <div class="card-title">问题清单</div>
          <div v-for="(it, i) in result.data.review.issues" :key="i" class="list-item" style="display:block">
            <div class="row" style="align-items:baseline;gap:8px">
              <span class="tag" :class="sevClass(it.severity)">{{ it.severity }}</span>
              <span style="font-size:13px;font-weight:500">{{ it.problem }}</span>
              <span class="tiny">{{ it.location }}</span>
            </div>
            <div class="muted" style="font-size:12.5px;margin-top:5px">{{ it.suggestion }}</div>
          </div>
        </div>

        <div class="card mt-16">
          <div class="card-title">答辩预判问题</div>
          <ol style="padding-left:20px;list-style:decimal;font-size:13.5px;line-height:2">
            <li v-for="(q, i) in result.data.review.defense_questions" :key="i">{{ q }}</li>
          </ol>
        </div>

        <details class="card mt-16">
          <summary style="cursor:pointer;font-size:13.5px;font-weight:500">Agent 执行轨迹</summary>
          <div class="trace-body mt-16">
            <div v-for="(t, i) in result.trace" :key="i" class="trace-node">
              <b>{{ t.node }}</b> · {{ t.description }} <span class="ms">{{ t.duration_ms }}ms</span>
            </div>
          </div>
        </details>
      </div>
    </div>`,
  };

  // 示例材料（故意留有缺陷）
  ReviewView.methods.demoText = function () {
    return `一、项目概述
本项目具有重要意义，旨在积极探索人工智能在教育领域的应用，通过先进技术手段有效推动教学模式变革，大大提升学习效率。

二、背景分析
随着信息技术的不断发展，教育信息化已经成为不可逆转的趋势。国家出台了多项政策支持教育数字化转型，各类院校纷纷开展探索。在这样的背景下，我们提出了本项目。

三、技术方案
本项目采用先进的人工智能技术，构建智能化学习平台。系统包括前端、后端和算法模块，前端负责界面展示，后端负责数据处理，算法模块负责智能分析。整体架构清晰，具有良好的扩展性。

四、预期成果
项目将形成一套完整的智能学习系统，申请软件著作权一项，发表论文一篇。

五、团队分工
团队成员分工明确，各司其职，相互配合，共同推进项目开展。`;
  };

  /* ================================================================ 数据统计 */
  const StatsView = {
    data() {
      return {
        overview: {},
        dims: { groups: {} },
        groupBy: "year",
        filters: { year: "", level: "", award_level: "", competition: "" },
        stats: null,
        question: "",
        askResult: null,
        loading: false,
        err: "",
        exporting: false,
        tab: "chart",
      };
    },
    mounted() {
      this.load();
    },
    computed: {
      trendOption() {
        const items = this.overview.year_trend || [];
        return {
          tooltip: { trigger: "axis" },
          legend: { right: 0, top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#6e6e73" } },
          grid: { left: 8, right: 8, top: 36, bottom: 4, containLabel: true },
          xAxis: {
            type: "category",
            data: items.map((i) => i.key),
            axisLine: { lineStyle: { color: "#e8e8ed" } },
            axisTick: { show: false },
            axisLabel: { color: "#6e6e73", fontSize: 11 },
          },
          yAxis: {
            type: "value",
            splitLine: { lineStyle: { color: "#f0f0f2" } },
            axisLabel: { color: "#96969b", fontSize: 11 },
          },
          series: [
            { name: "参赛项目", type: "bar", data: items.map((i) => i.count), itemStyle: { color: "#1d1d1f", borderRadius: [3, 3, 0, 0] }, barMaxWidth: 26 },
            { name: "获奖", type: "bar", data: items.map((i) => i.award_count), itemStyle: { color: "#0071e3", borderRadius: [3, 3, 0, 0] }, barMaxWidth: 26 },
          ],
        };
      },
      awardOption() {
        const items = (this.overview.award_distribution || []).filter((i) => i.count > 0);
        return {
          tooltip: { trigger: "item", formatter: "{b}：{c} 项（{d}%）" },
          legend: { bottom: 0, itemWidth: 9, itemHeight: 9, textStyle: { fontSize: 11, color: "#6e6e73" } },
          color: ["#1d1d1f", "#0071e3", "#5b8def", "#9ab8e8", "#c9d8f0"],
          series: [
            {
              type: "pie",
              radius: ["46%", "68%"],
              center: ["50%", "44%"],
              avoidLabelOverlap: true,
              itemStyle: { borderColor: "#fff", borderWidth: 2 },
              label: { show: false },
              data: items.map((i) => ({ name: i.key, value: i.count })),
            },
          ],
        };
      },
      levelOption() {
        const items = this.overview.level_distribution || [];
        return {
          tooltip: { trigger: "axis" },
          grid: { left: 8, right: 16, top: 16, bottom: 4, containLabel: true },
          xAxis: {
            type: "value",
            splitLine: { lineStyle: { color: "#f0f0f2" } },
            axisLabel: { color: "#96969b", fontSize: 11 },
          },
          yAxis: {
            type: "category",
            data: items.map((i) => i.key),
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: "#6e6e73", fontSize: 11 },
          },
          series: [
            {
              type: "bar",
              data: items.map((i) => i.count),
              itemStyle: { color: "#1d1d1f", borderRadius: [0, 3, 3, 0] },
              barMaxWidth: 20,
            },
          ],
        };
      },
      groupOption() {
        if (!this.stats) return {};
        const items = this.stats.items.slice(0, 12);
        return {
          tooltip: { trigger: "axis" },
          legend: { right: 0, top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#6e6e73" } },
          grid: { left: 8, right: 8, top: 36, bottom: 4, containLabel: true },
          xAxis: {
            type: "category",
            data: items.map((i) => i.key),
            axisLine: { lineStyle: { color: "#e8e8ed" } },
            axisTick: { show: false },
            axisLabel: { color: "#6e6e73", fontSize: 11, interval: 0, rotate: items.length > 6 ? 30 : 0 },
          },
          yAxis: [
            { type: "value", splitLine: { lineStyle: { color: "#f0f0f2" } }, axisLabel: { color: "#96969b", fontSize: 11 } },
            { type: "value", splitLine: { show: false }, axisLabel: { color: "#96969b", fontSize: 11, formatter: "{value}%" } },
          ],
          series: [
            { name: "参赛", type: "bar", data: items.map((i) => i.count), itemStyle: { color: "#1d1d1f", borderRadius: [3, 3, 0, 0] }, barMaxWidth: 24 },
            { name: "获奖", type: "bar", data: items.map((i) => i.award_count), itemStyle: { color: "#0071e3", borderRadius: [3, 3, 0, 0] }, barMaxWidth: 24 },
            { name: "获奖率", type: "line", yAxisIndex: 1, data: items.map((i) => i.award_rate), lineStyle: { color: "#b8b8bd", width: 1.5 }, itemStyle: { color: "#b8b8bd" }, symbolSize: 4 },
          ],
        };
      },
    },
    methods: {
      async load() {
        this.loading = true;
        try {
          const [ov, dims] = await Promise.all([API.overview(), API.dimensions()]);
          this.overview = ov;
          this.dims = dims;
          await this.query();
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      async query() {
        try {
          this.stats = await API.statistics({ group_by: this.groupBy, ...this.filters });
        } catch (e) {
          this.err = e.message;
        }
      },
      async ask() {
        if (!this.question.trim()) return;
        this.loading = true;
        this.err = "";
        try {
          this.askResult = await API.statisticsAsk(this.question);
          if (this.askResult.data && this.askResult.data.stats) {
            this.stats = this.askResult.data.stats;
            this.groupBy = this.stats.group_by;
          }
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      async exportExcel() {
        this.exporting = true;
        try {
          const res = await API.post(
            "/api/data/statistics/export" + "?group_by=" + this.groupBy +
              "&year=" + (this.filters.year || "") +
              "&level=" + (this.filters.level || "") +
              "&award_level=" + (this.filters.award_level || "") +
              "&competition=" + (this.filters.competition || ""),
            {}
          );
          window.location.href = res.download_url;
        } catch (e) {
          this.err = e.message;
        } finally {
          this.exporting = false;
        }
      },
      fmt(n) {
        return (n || 0).toLocaleString();
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>竞赛数据统计</h2>
        <p>全部数字由数据库聚合得出，不经过大模型生成。支持按年度、赛项、专业、教师、获奖级别等维度交叉统计，结果可导出 Excel。</p>
      </div>

      <div class="grid grid-4">
        <stat label="参赛项目" :value="fmt(overview.team_count)" unit="项" :sub="'覆盖 ' + (overview.years||[]).length + ' 个年度'" />
        <stat label="获奖总数" :value="fmt(overview.award_count)" unit="项" :sub="'获奖率 ' + (overview.award_rate||0) + '%'" />
        <stat label="国家级获奖" :value="fmt(overview.national_award)" unit="项" :sub="'省级 ' + (overview.provincial_award||0) + ' 项'" />
        <stat label="经费总额" :value="fmt(Math.round(overview.budget_total||0))" unit="元" />
      </div>

      <div class="grid grid-2 mt-16">
        <div class="card">
          <div class="card-title">年度趋势 <small>参赛与获奖</small></div>
          <chart :option="trendOption" height="260px" />
        </div>
        <div class="card">
          <div class="card-title">获奖等级分布</div>
          <chart :option="awardOption" height="260px" />
        </div>
      </div>

      <div class="card mt-16">
        <div class="card-title">
          <span>维度查询</span>
          <button class="btn btn-sm" @click="exportExcel" :disabled="exporting">
            <icon name="download" :size="13" /> {{ exporting ? '导出中…' : '导出 Excel' }}
          </button>
        </div>

        <div class="chip-row" style="margin-bottom:14px">
          <button v-for="(label, key) in dims.groups" :key="key" class="chip"
                  :class="{active: groupBy === key}" @click="groupBy = key; query()">
            {{ label }}
          </button>
        </div>

        <div class="row wrap" style="margin-bottom:16px">
          <div class="field" style="width:120px">
            <label>年份</label>
            <input class="input" v-model="filters.year" placeholder="全部" @change="query" />
          </div>
          <div class="field" style="width:140px">
            <label>赛事级别</label>
            <select class="select" v-model="filters.level" @change="query">
              <option value="">全部</option>
              <option>国家级</option><option>省级</option><option>校级</option><option>行业级</option>
            </select>
          </div>
          <div class="field" style="width:140px">
            <label>获奖等级</label>
            <select class="select" v-model="filters.award_level" @change="query">
              <option value="">全部</option>
              <option>特等奖</option><option>一等奖</option><option>二等奖</option>
              <option>三等奖</option><option>优秀奖</option>
            </select>
          </div>
          <div class="field grow">
            <label>赛事关键词</label>
            <input class="input" v-model="filters.competition" placeholder="如 国创赛" @change="query" />
          </div>
        </div>

        <div class="row" style="margin-bottom:14px">
          <input class="input grow" v-model="question" placeholder="或者直接问：2025 年各专业的获奖情况" @keyup.enter="ask" />
          <button class="btn" @click="ask" :disabled="loading">问数</button>
        </div>

        <div v-if="askResult" class="alert alert-info" style="margin-bottom:14px;white-space:pre-wrap">{{ askResult.answer }}</div>

        <div v-if="stats" class="grid grid-2" style="align-items:start">
          <chart :option="groupOption" height="300px" />
          <div style="max-height:300px;overflow-y:auto">
            <table class="table">
              <thead>
                <tr><th>{{ stats.group_label }}</th><th class="num">参赛</th><th class="num">获奖</th><th class="num">获奖率</th></tr>
              </thead>
              <tbody>
                <tr v-for="it in stats.items" :key="it.key">
                  <td>{{ it.key }}</td>
                  <td class="num">{{ it.count }}</td>
                  <td class="num">{{ it.award_count }}</td>
                  <td class="num">{{ it.award_rate }}%</td>
                </tr>
                <tr style="font-weight:600;background:var(--bg-sub)">
                  <td>合计</td>
                  <td class="num">{{ stats.totals.count }}</td>
                  <td class="num">{{ stats.totals.award_count }}</td>
                  <td class="num">{{ stats.totals.award_rate }}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="card mt-16">
        <div class="card-title">教师指导学生工作量</div>
        <chart :option="levelOption" height="220px" />
        <div class="grid grid-2 mt-16">
          <div>
            <div class="tiny" style="margin-bottom:8px">教师排行</div>
            <div v-for="(t, i) in (overview.teacher_top || []).slice(0,6)" :key="i" class="list-item" style="padding:8px 0">
              <span class="rank-no">{{ i + 1 }}</span>
              <span style="font-size:13px">{{ t.key }}</span>
              <span style="flex:1"></span>
              <span class="tiny">{{ t.count }} 项 / 获奖 {{ t.award_count }}</span>
            </div>
          </div>
          <div>
            <div class="tiny" style="margin-bottom:8px">赛事级别分布</div>
            <div v-for="(l, i) in (overview.level_distribution || [])" :key="i" class="list-item" style="padding:8px 0">
              <span style="font-size:13px">{{ l.key }}</span>
              <span style="flex:1"></span>
              <span class="tiny">{{ l.count }} 项 · 获奖率 {{ l.award_rate }}%</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="err" class="alert alert-err mt-16">{{ err }}</div>
    </div>`,
  };

  /* ================================================================ 经费 */
  const FinanceView = {
    data() {
      return {
        tab: "budget",
        rules: null,
        teams: [],
        teamId: "",
        form: { competition: "", team_name: "", level: "国家级", people: 3, days: 3, fee: 300, is_local: false, distance: "省外" },
        budget: null,
        loan: null,
        reimburse: { items: [], budgetAmount: 0, attachments: [] },
        reimburseResult: null,
        loading: false,
        msg: "",
        err: "",
      };
    },
    mounted() {
      this.load();
    },
    methods: {
      async load() {
        try {
          this.rules = await API.budgetRules();
          this.teams = await API.teamsOptions("");
        } catch (e) {
          this.err = e.message;
        }
      },
      async pickTeam() {
        const t = this.teams.find((x) => String(x.id) === String(this.teamId));
        if (!t) return;
        this.form.competition = t.competition;
        this.form.team_name = t.project;
        this.form.level = t.level;
        this.reimburse.budgetAmount = this.budget ? this.budget.total : 0;
      },
      async compute() {
        this.loading = true;
        this.err = "";
        try {
          this.budget = await API.budgetCompute(this.form);
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      async exportBudget() {
        try {
          const res = await API.budgetExport(this.form);
          window.location.href = res.download_url;
          this.msg = "预算申请表已生成：" + res.filename;
        } catch (e) {
          this.err = e.message;
        }
      },
      async buildLoan() {
        this.loading = true;
        this.err = "";
        try {
          this.loan = await API.loanBuild({
            team_id: this.teamId || null,
            amount: this.budget ? this.budget.total : 0,
            people: this.form.people,
            distance: this.form.distance,
          });
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      async exportLoan() {
        try {
          const res = await API.loanExport({
            team_id: this.teamId || null,
            amount: this.loan.amount,
            people: this.form.people,
            distance: this.form.distance,
          });
          window.location.href = res.download_url;
        } catch (e) {
          this.err = e.message;
        }
      },
      addItem() {
        this.reimburse.items.push({ name: "", amount: 0, invoice_no: "", invoice_date: "", invoice_type: "增值税普通发票" });
      },
      removeItem(i) {
        this.reimburse.items.splice(i, 1);
      },
      async checkReimburse() {
        this.loading = true;
        this.err = "";
        try {
          this.reimburseResult = await API.reimburseCheck({
            items: this.reimburse.items,
            budget_amount: this.reimburse.budgetAmount,
            attachments: this.reimburse.attachments,
          });
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      async exportReimburse() {
        try {
          const res = await API.reimburseExport({
            items: this.reimburse.items,
            budget_amount: this.reimburse.budgetAmount,
            attachments: this.reimburse.attachments,
          });
          window.location.href = res.download_url;
        } catch (e) {
          this.err = e.message;
        }
      },
      toggleAttach(a) {
        const i = this.reimburse.attachments.indexOf(a);
        if (i >= 0) this.reimburse.attachments.splice(i, 1);
        else this.reimburse.attachments.push(a);
      },
      lvClass(l) {
        return { 高: "tag-danger", 中: "tag-warn", 低: "tag" }[l] || "tag";
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>经费辅助</h2>
        <p>按开支标准测算预算、填制借款单、预审报销材料，一键导出规范 Word 单据。开支标准存于数据库，改标准不用改代码。</p>
      </div>

      <div class="seg" style="margin-bottom:20px">
        <button :class="{active: tab==='budget'}" @click="tab='budget'">预算申请</button>
        <button :class="{active: tab==='loan'}" @click="tab='loan'">借款</button>
        <button :class="{active: tab==='reimburse'}" @click="tab='reimburse'">报销</button>
      </div>

      <div v-if="err" class="alert alert-err" style="margin-bottom:16px">{{ err }}</div>
      <div v-if="msg" class="alert alert-ok" style="margin-bottom:16px">{{ msg }}</div>

      <!-- 预算 -->
      <div v-if="tab === 'budget'" class="grid" style="grid-template-columns: 1fr 1.35fr; align-items:start">
        <div class="card">
          <div class="card-title">参赛信息</div>
          <div class="field">
            <label>关联参赛项目（可选）</label>
            <select class="select" v-model="teamId" @change="pickTeam">
              <option value="">手动填写</option>
              <option v-for="t in teams" :key="t.id" :value="t.id">
                {{ t.year }} {{ t.competition }} · {{ t.project }}
              </option>
            </select>
          </div>
          <div class="grid grid-2 mt-16">
            <div class="field">
              <label>赛事名称</label>
              <input class="input" v-model="form.competition" />
            </div>
            <div class="field">
              <label>队伍/项目名称</label>
              <input class="input" v-model="form.team_name" />
            </div>
            <div class="field">
              <label>参赛人数</label>
              <input class="input" type="number" v-model.number="form.people" min="1" />
            </div>
            <div class="field">
              <label>赛程天数</label>
              <input class="input" type="number" v-model.number="form.days" min="1" />
            </div>
            <div class="field">
              <label>报名费（元）</label>
              <input class="input" type="number" v-model.number="form.fee" min="0" />
            </div>
            <div class="field">
              <label>参赛地点</label>
              <select class="select" v-model="form.distance">
                <option>本地</option><option>省内</option><option>省外</option>
              </select>
            </div>
          </div>
          <button class="btn btn-primary mt-16" style="width:100%" @click="compute" :disabled="loading">
            {{ loading ? '测算中…' : '测算预算' }}
          </button>
          <div class="tiny mt-16">
            当前标准版本：{{ rules ? rules.title : '加载中' }}
          </div>
        </div>

        <div class="card" v-if="budget">
          <div class="card-title">
            <span>预算明细</span>
            <span class="mono" style="font-size:18px;font-weight:600">{{ budget.total.toFixed(2) }} 元</span>
          </div>
          <table class="table">
            <thead><tr><th>科目</th><th>说明</th><th class="num">数量</th><th class="num">单价</th><th class="num">金额</th></tr></thead>
            <tbody>
              <tr v-for="(it, i) in budget.items" :key="i">
                <td>{{ it.name }}</td>
                <td class="tiny">{{ it.spec }}</td>
                <td class="num">{{ it.qty }}</td>
                <td class="num">{{ it.price.toFixed(2) }}</td>
                <td class="num">{{ it.amount.toFixed(2) }}</td>
              </tr>
              <tr style="font-weight:600;background:var(--bg-sub)">
                <td colspan="4">合计</td>
                <td class="num">{{ budget.total.toFixed(2) }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="budget.warnings.length" class="mt-16">
            <div class="tiny" style="margin-bottom:6px">校验提示</div>
            <div v-for="(w, i) in budget.warnings" :key="i" class="alert alert-warn" style="margin-bottom:6px">
              [{{ w.level }}] {{ w.item }}：{{ w.problem }}　建议：{{ w.advice }}
            </div>
          </div>

          <div class="mt-16">
            <div class="tiny" style="margin-bottom:6px">预算说明（可直接用于申请书）</div>
            <div class="muted" style="font-size:13px;line-height:1.8;background:var(--bg-sub);padding:14px;border-radius:10px">{{ budget.statement }}</div>
          </div>

          <button class="btn mt-16" @click="exportBudget"><icon name="download" :size="14" /> 导出 Word 预算申请表</button>
        </div>

        <div class="card" v-else>
          <div class="card-title">预算明细</div>
          <div class="muted" style="font-size:13px;line-height:1.9">
            <p style="margin:0 0 8px">填写左侧参赛信息，点击「测算预算」。</p>
            <p style="margin:0 0 8px">系统按学院经费开支标准逐项测算，给出明细表、超标预警，以及可直接粘贴进申请书的预算说明。</p>
            <p style="margin:0">所有金额均来自标准表与人数天数计算，不经模型生成。</p>
          </div>
        </div>
      </div>

      <!-- 借款 -->
      <div v-if="tab === 'loan'" class="grid" style="grid-template-columns: 1fr 1.35fr; align-items:start">
        <div class="card">
          <div class="card-title">借款依据</div>
          <div class="field">
            <label>选择参赛项目</label>
            <select class="select" v-model="teamId" @change="pickTeam">
              <option value="">请选择</option>
              <option v-for="t in teams" :key="t.id" :value="t.id">{{ t.year }} {{ t.competition }} · {{ t.project }}</option>
            </select>
          </div>
          <button class="btn btn-primary mt-16" style="width:100%" @click="buildLoan" :disabled="loading">
            {{ loading ? '生成中…' : '生成借款单要素' }}
          </button>
          <div class="tiny mt-16">借款金额不得超过已批复预算。未关联预算时按预算测算金额填制。</div>
        </div>

        <div class="card" v-if="loan">
          <div class="card-title">借款单要素</div>
          <div class="list-item"><span class="tiny" style="width:90px">金额</span><span class="mono" style="font-weight:600">{{ loan.amount.toFixed(2) }} 元</span></div>
          <div class="list-item"><span class="tiny" style="width:90px">大写</span><span>{{ loan.amount_cn }}</span></div>
          <div class="list-item"><span class="tiny" style="width:90px">用途</span><span>{{ loan.purpose }}</span></div>
          <div class="list-item"><span class="tiny" style="width:90px">经办人</span><span>{{ loan.borrower || '（待填）' }}</span></div>
          <div class="list-item"><span class="tiny" style="width:90px">关联预算</span><span>{{ loan.budget_no || '（未关联）' }}</span></div>
          <div class="list-item"><span class="tiny" style="width:90px">附单据</span><span>{{ loan.attachments.join('、') }}</span></div>
          <div v-for="(w, i) in loan.warnings" :key="i" class="alert alert-warn mt-8">[{{ w.level }}] {{ w.problem }}　{{ w.advice }}</div>
          <button class="btn mt-16" @click="exportLoan"><icon name="download" :size="14" /> 导出 Word 借款单</button>
        </div>

        <div class="card" v-else>
          <div class="card-title">借款单要素</div>
          <div class="muted" style="font-size:13px;line-height:1.9">
            <p style="margin:0 0 8px">选择已批复的参赛项目，或先测算预算，再生成借款单。</p>
            <p style="margin:0">系统自动填好大写金额、用途、经办人与附单据清单，导出即为可直接打印的 Word 借款单。</p>
          </div>
        </div>
      </div>

      <!-- 报销 -->
      <div v-if="tab === 'reimburse'" class="grid" style="grid-template-columns: 1.3fr 1fr; align-items:start">
        <div class="card">
          <div class="card-title">
            <span>报销明细</span>
            <button class="btn btn-sm" @click="addItem"><icon name="plus" :size="13" /> 添加一行</button>
          </div>
          <div class="field">
            <label>批复预算金额（元）</label>
            <input class="input" type="number" v-model.number="reimburse.budgetAmount" />
          </div>
          <table class="table mt-16">
            <thead><tr><th>支出事项</th><th style="width:90px">金额</th><th style="width:120px">发票号</th><th style="width:120px">开票日期</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(it, i) in reimburse.items" :key="i">
                <td><input class="input" v-model="it.name" placeholder="如 高铁票" /></td>
                <td><input class="input" type="number" v-model.number="it.amount" /></td>
                <td><input class="input" v-model="it.invoice_no" /></td>
                <td><input class="input" v-model="it.invoice_date" placeholder="2026-05-20" /></td>
                <td><button class="btn btn-ghost btn-sm" @click="removeItem(i)">删</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!reimburse.items.length" class="empty">点击「添加一行」录入票据</div>

          <div class="mt-16">
            <div class="tiny" style="margin-bottom:8px">已备附件</div>
            <div class="chip-row">
              <button v-for="a in ['竞赛通知','参赛审批表','发票原件','行程单或签到表','预算批复单','获奖证书']" :key="a"
                      class="chip" :class="{active: reimburse.attachments.includes(a)}" @click="toggleAttach(a)">{{ a }}</button>
            </div>
          </div>

          <div class="row mt-16">
            <button class="btn btn-primary" @click="checkReimburse" :disabled="loading">预审</button>
            <button class="btn" @click="exportReimburse"><icon name="download" :size="14" /> 导出报销单</button>
          </div>
        </div>

        <div class="card" v-if="reimburseResult">
          <div class="card-title">审核结论</div>
          <div class="alert" :class="reimburseResult.pass ? 'alert-ok' : 'alert-warn'">{{ reimburseResult.conclusion }}</div>
          <div class="grid grid-3 mt-16">
            <stat label="实际支出" :value="reimburseResult.total.toFixed(0)" unit="元" />
            <stat label="批复预算" :value="reimburseResult.approved.toFixed(0)" unit="元" />
            <stat label="超支" :value="reimburseResult.over_budget.toFixed(0)" unit="元" />
          </div>
          <div v-if="reimburseResult.issues.length" class="mt-16">
            <div class="tiny" style="margin-bottom:6px">问题清单</div>
            <div v-for="(it, i) in reimburseResult.issues" :key="i" class="list-item" style="display:block">
              <div class="row" style="gap:8px;align-items:baseline">
                <span class="tag" :class="lvClass(it.level)">{{ it.level }}</span>
                <span style="font-size:13px">{{ it.item }}：{{ it.problem }}</span>
              </div>
              <div class="tiny" style="margin-top:3px">处理：{{ it.fix }}</div>
            </div>
          </div>
          <div v-if="reimburseResult.missing_attachments.length" class="alert alert-warn mt-16">
            缺失附件：{{ reimburseResult.missing_attachments.join('、') }}
          </div>
        </div>

        <div class="card" v-else>
          <div class="card-title">审核结论</div>
          <div class="muted" style="font-size:13px;line-height:1.9">
            <p style="margin:0 0 8px">录入票据明细后点击「预审」，系统按报销细则逐项校验。</p>
            <p style="margin:0">检查项包括：发票号与开票日期是否齐全、科目是否在开支范围、合计是否超批复预算、附件是否齐备。</p>
          </div>
        </div>
      </div>
    </div>`,
  };

  /* ================================================================ 系统 */
  const SystemView = {
    data() {
      return {
        health: null,
        workflows: [],
        tools: [],
        runs: [],
        activeWf: null,
        err: "",
      };
    },
    mounted() {
      this.load();
    },
    methods: {
      async load() {
        try {
          const [h, w, t, r] = await Promise.all([
            API.health(), API.workflows(), API.tools(), API.runs(),
          ]);
          this.health = h;
          this.workflows = w;
          this.tools = t;
          this.runs = r;
          this.activeWf = w[0] || null;
        } catch (e) {
          this.err = e.message;
        }
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>系统状态</h2>
        <p>智能体工作流按节点编排，每个节点的输入输出都可追溯。工具层封装确定性的数据查询与计算，模型只负责理解与表述。</p>
      </div>

      <div class="card" v-if="health">
        <div class="card-title">运行环境</div>
        <div class="grid grid-3">
          <div class="list-item" style="border:none">
            <span class="tiny" style="width:80px">大模型</span>
            <span>{{ health.llm.provider }} / {{ health.llm.model }}</span>
          </div>
          <div class="list-item" style="border:none">
            <span class="tiny" style="width:80px">状态</span>
            <span class="tag" :class="health.llm.available ? 'tag-ok' : 'tag-warn'">
              {{ health.llm.available ? '已接入' : '未配置（抽取式回答）' }}
            </span>
          </div>
          <div class="list-item" style="border:none">
            <span class="tiny" style="width:80px">向量方式</span>
            <span>{{ health.llm.embedding_mode }}</span>
          </div>
        </div>
        <div v-if="!health.llm.available" class="alert alert-info mt-16">
          当前未配置大模型 API Key，问答走原文抽取模式（只重组检索到的原句，不生成新内容）。
          在项目根目录 .env 中填写 LLM_PROVIDER 与 LLM_API_KEY 后重启即可切换为模型生成。
        </div>
        <div v-if="health.llm.last_error" class="alert alert-err mt-8">最近一次调用错误：{{ health.llm.last_error }}</div>
      </div>

      <div class="card mt-16">
        <div class="card-title">工作流编排 <small>{{ workflows.length }} 条</small></div>
        <div class="chip-row" style="margin-bottom:16px">
          <button v-for="w in workflows" :key="w.key" class="chip"
                  :class="{active: activeWf && activeWf.key === w.key}" @click="activeWf = w">{{ w.label }}</button>
        </div>
        <div v-if="activeWf">
          <div class="grid grid-3">
            <div v-for="n in activeWf.graph.nodes" :key="n.name" class="workflow-node">
              <div class="n">{{ n.name }}</div>
              <div class="d">{{ n.description }}</div>
              <div class="tiny" style="margin-top:4px">
                <span v-if="n.next.type === 'edge'">→ {{ n.next.target }}</span>
                <span v-else>→ 条件分支：{{ Object.keys(n.next.branches).join(' / ') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="grid grid-2 mt-16" style="align-items:start">
        <div class="card">
          <div class="card-title">工具清单 <small>{{ tools.length }} 个</small></div>
          <div v-for="t in tools" :key="t.name" class="list-item" style="display:block;padding:10px 0">
            <div class="mono" style="font-size:12.5px;font-weight:500">{{ t.name }}</div>
            <div class="tiny">{{ t.description }}</div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">最近执行记录</div>
          <div v-if="runs.length">
            <div v-for="r in runs.slice(0,12)" :key="r.id" class="list-item">
              <span class="tag">{{ r.label }}</span>
              <span class="tiny">{{ r.steps }} 节点</span>
              <span style="flex:1"></span>
              <span class="tiny mono">{{ r.duration_ms }} ms</span>
              <span class="tiny">{{ r.created_at }}</span>
            </div>
          </div>
          <div v-else class="empty">还没有执行记录</div>
        </div>
      </div>

      <div v-if="err" class="alert alert-err mt-16">{{ err }}</div>
    </div>`,
  };

  window.Views = Object.assign(window.Views || {}, {
    ReviewView,
    StatsView,
    FinanceView,
    SystemView,
  });
})();
