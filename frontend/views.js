/* 页面：智能问答 / 知识库 / 竞赛推荐 / 备赛辅助 */
(function () {
  const { renderMarkdown } = window.Components;

  const isMarkdown = (t) => /^##\s/m.test(t || "") || /\n\s*\|[^\n]*\|/.test(t || "");

  /* ================================================================ 问答 */
  const ChatView = {
    data() {
      return {
        messages: [],
        input: "",
        loading: false,
        conversations: [],
        currentConv: null,
        error: "",
        sendHint: "",
        llmMode: "",
        expandedCite: {},
        panel: null,
        suggestions: [
          "国创赛校赛的报名截止时间是什么时候？",
          "ACM 区域赛允许带纸质资料吗？",
          "省外参赛住宿费标准是多少？",
          "报销需要准备哪些材料？",
          "申报书缺少实验数据会扣多少分？",
        ],
      };
    },
    computed: {
      canSend() {
        return this.input.trim() && !this.loading;
      },
    },
    mounted() {
      this.loadConversations();
    },
    methods: {
      isMd: isMarkdown,
      md: renderMarkdown,
      async loadConversations() {
        try {
          this.conversations = await API.conversations();
        } catch (e) {
          /* 忽略 */
        }
      },
      async openConv(id) {
        try {
          const c = await API.conversation(id);
          this.currentConv = c.id;
          this.messages = c.messages;
        } catch (e) {
          this.error = e.message;
        }
      },
      newConv() {
        this.currentConv = null;
        this.messages = [];
        this.error = "";
      },
      async delConv(id, ev) {
        ev.stopPropagation();
        if (!confirm("删除该对话？")) return;
        await API.delConversation(id);
        if (this.currentConv === id) this.newConv();
        this.loadConversations();
      },
      useSuggestion(s) {
        this.input = s;
        this.send();
      },
      async send() {
        const q = this.input.trim();
        if (!q || this.loading) return;
        this.input = "";
        this.error = "";
        this.messages.push({ role: "user", content: q });
        this.loading = true;
        try {
          const res = await API.ask(q, this.currentConv);
          this.currentConv = res.conversation_id;
          this.messages.push({
            role: "assistant",
            content: res.answer,
            citations: res.citations || [],
            meta: { mode: res.mode, duration_ms: res.duration_ms },
            trace: res.trace || [],
          });
          this.llmMode = res.mode;
          this.loadConversations();
        } catch (e) {
          this.error = e.message;
        } finally {
          this.loading = false;
        }
      },
      onKey(e) {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") this.send();
      },
      toggleCite(key) {
        this.expandedCite[key] = !this.expandedCite[key];
      },
      async showChunk(c) {
        try {
          this.panel = await API.chunk(c.chunk_id);
        } catch (e) {
          this.panel = { title: c.title, content: c.snippet, filename: c.filename };
        }
      },
      closePanel() {
        this.panel = null;
      },
      modeLabel(m) {
        return { llm: "大模型生成", extractive: "原文抽取", no_hit: "未收录" }[m] || m;
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>竞赛知识问答</h2>
        <p>基于学院竞赛政策、规程与通知构建的知识库作答，每个结论都附原文出处。知识库没有的内容会直接说明，不作推测。</p>
      </div>

      <div class="chat-shell">
        <div class="chat-side">
          <button class="btn btn-sm" style="width:100%" @click="newConv">
            <icon name="plus" :size="14" /> 新建对话
          </button>
          <div style="overflow-y:auto; flex:1">
            <div v-for="c in conversations" :key="c.id"
                 class="conv-item" :class="{active: currentConv === c.id}"
                 @click="openConv(c.id)">
              <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ c.title }}</span>
              <span style="color:var(--text-3);font-size:11px;flex:0 0 auto">{{ c.message_count }}</span>
            </div>
            <div v-if="!conversations.length" class="tiny" style="padding:10px">暂无对话</div>
          </div>
        </div>

        <div class="chat-main">
          <div class="chat-scroll" ref="scroll">
            <div v-if="!messages.length" style="padding-top:40px">
              <div class="center" style="margin-bottom:26px">
                <div style="font-size:22px;font-weight:600;letter-spacing:-0.02em">问点什么？</div>
                <div class="muted" style="margin-top:6px;font-size:13px">赛事时间、材料要求、经费标准、评审规则，都可以问。</div>
              </div>
              <div class="suggest" style="justify-content:center">
                <button v-for="s in suggestions" :key="s" @click="useSuggestion(s)">{{ s }}</button>
              </div>
            </div>

            <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role === 'user' ? 'msg-user' : 'msg-ai'">
              <div v-if="m.role === 'user'" class="bubble">{{ m.content }}</div>
              <div v-else>
                <div class="who">
                  <span class="tag" :class="m.meta && m.meta.mode === 'llm' ? 'tag-accent' : ''">
                    {{ modeLabel(m.meta && m.meta.mode) }}
                  </span>
                  <span v-if="m.meta && m.meta.duration_ms">{{ m.meta.duration_ms }} ms</span>
                </div>
                <div v-if="isMd(m.content)" class="body md" v-html="md(m.content)"></div>
                <div v-else class="body" style="white-space:pre-wrap">{{ m.content }}</div>

                <div v-if="m.citations && m.citations.length" class="citations">
                  <div class="tiny" style="margin-bottom:2px">引用来源</div>
                  <div v-for="(c, ci) in m.citations" :key="ci" class="cite">
                    <div class="cite-head">
                      <span class="cite-idx">{{ ci + 1 }}</span>
                      <span class="cite-title">{{ c.title }}</span>
                      <span class="tag">{{ c.category }}</span>
                      <span v-if="c.page" class="tiny">第 {{ c.page }} 页</span>
                      <span style="flex:1"></span>
                      <button class="btn btn-ghost btn-sm" @click="showChunk(c)">查看原文</button>
                    </div>
                    <div class="cite-body">{{ c.snippet }}</div>
                  </div>
                </div>

                <details v-if="m.trace && m.trace.length" class="trace">
                  <summary>Agent 执行过程（{{ m.trace.length }} 个节点）</summary>
                  <div class="trace-body">
                    <div v-for="(t, ti) in m.trace" :key="ti" class="trace-node">
                      <b>{{ t.node }}</b> · {{ t.description }}
                      <span class="ms">{{ t.duration_ms }}ms</span>
                    </div>
                  </div>
                </details>
              </div>
            </div>

            <div v-if="loading" class="msg msg-ai">
              <div class="who">正在检索知识库并组织回答</div>
              <div><span class="spinner"></span></div>
            </div>
            <div v-if="error" class="alert alert-err mt-16">{{ error }}</div>
          </div>

          <div class="chat-input">
            <textarea v-model="input" rows="1" placeholder="输入问题，Ctrl+Enter 发送"
                      @keydown="onKey"></textarea>
            <button class="btn btn-primary" :disabled="!canSend" @click="send">
              <icon name="send" :size="14" /> 发送
            </button>
          </div>
        </div>
      </div>

      <div v-if="panel" class="card mt-16">
        <div class="card-title">
          <span>{{ panel.title }} <small v-if="panel.filename">· {{ panel.filename }}</small></span>
          <button class="btn btn-ghost btn-sm" @click="closePanel"><icon name="close" :size="14" /></button>
        </div>
        <div class="tiny" style="margin-bottom:8px">
          片段 #{{ panel.seq }} <span v-if="panel.heading">· {{ panel.heading }}</span>
          <span v-if="panel.page">· 第 {{ panel.page }} 页</span>
        </div>
        <div class="md" style="white-space:pre-wrap;line-height:1.8">{{ panel.content }}</div>
      </div>
    </div>`,
  };

  /* ================================================================ 知识库 */
  const KnowledgeView = {
    data() {
      return {
        docs: [],
        stats: {},
        loading: true,
        uploading: false,
        category: "",
        year: "",
        query: "",
        results: [],
        searching: false,
        msg: "",
        err: "",
      };
    },
    mounted() {
      this.load();
    },
    methods: {
      async load() {
        this.loading = true;
        try {
          const res = await API.knowledgeDocs();
          this.docs = res.items;
          this.stats = res.stats;
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      async onFile(e) {
        const files = Array.from(e.target.files || []);
        if (!files.length) return;
        await this.upload(files);
        e.target.value = "";
      },
      async onDrop(e) {
        e.preventDefault();
        const files = Array.from(e.dataTransfer.files || []);
        if (files.length) await this.upload(files);
      },
      async upload(files) {
        this.uploading = true;
        this.msg = "";
        this.err = "";
        const fd = new FormData();
        files.forEach((f) => fd.append("files", f));
        fd.append("category", this.category);
        fd.append("year", this.year);
        try {
          const res = await API.upload("/api/knowledge/upload", fd);
          this.msg = `导入完成：成功 ${res.ok} 份` + (res.failed ? `，失败 ${res.failed} 份` : "");
          if (res.errors && res.errors.length) {
            this.err = res.errors.map((x) => `${x.file}: ${x.error}`).join("；");
          }
          await this.load();
        } catch (e) {
          this.err = e.message;
        } finally {
          this.uploading = false;
        }
      },
      async remove(d) {
        if (!confirm(`删除《${d.title}》？该文档的检索片段将一并移除。`)) return;
        try {
          await API.knowledgeDelete(d.id);
          await this.load();
        } catch (e) {
          this.err = e.message;
        }
      },
      async search() {
        if (!this.query.trim()) return;
        this.searching = true;
        try {
          const res = await API.knowledgeSearch(this.query, 8);
          this.results = res.items;
        } catch (e) {
          this.err = e.message;
        } finally {
          this.searching = false;
        }
      },
      async rebuild() {
        this.msg = "正在重建索引…";
        try {
          const res = await API.knowledgeRebuild();
          this.msg = `索引已重建，共 ${res.chunks} 个片段`;
          await this.load();
        } catch (e) {
          this.err = e.message;
        }
      },
      fmt(n) {
        return (n || 0).toLocaleString();
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>知识库</h2>
        <p>支持 PDF、Word、Excel、Markdown、TXT。导入后自动切块并建立关键词与语义双索引，问答时按片段引用原文。</p>
      </div>

      <div class="grid grid-4">
        <stat label="收录文档" :value="stats.doc_count || 0" unit="份" />
        <stat label="检索片段" :value="fmt(stats.chunk_count)" unit="个" />
        <stat label="文本总量" :value="fmt(Math.round((stats.char_count||0)/1000))" unit="千字" />
        <stat label="文档类别" :value="Object.keys(stats.by_category || {}).length" unit="类" />
      </div>

      <div class="grid grid-2 mt-16">
        <div class="card">
          <div class="card-title">上传文档</div>
          <div class="upload-zone"
               @click="$refs.file.click()"
               @dragover.prevent
               @drop="onDrop">
            <strong>{{ uploading ? '正在解析入库…' : '点击选择，或把文件拖到这里' }}</strong>
            <span class="tiny">支持 .pdf .docx .xlsx .csv .md .txt，可多选</span>
            <input ref="file" type="file" multiple class="hidden" @change="onFile"
                   accept=".pdf,.docx,.xlsx,.csv,.md,.txt" />
          </div>
          <div class="row mt-16">
            <div class="field grow">
              <label>文档类别</label>
              <select class="select" v-model="category">
                <option value="">自动识别</option>
                <option>政策</option>
                <option>规程</option>
                <option>通知</option>
                <option>模板</option>
                <option>其他</option>
              </select>
            </div>
            <div class="field grow">
              <label>年份（可空）</label>
              <input class="input" v-model="year" placeholder="如 2026" />
            </div>
          </div>
          <div v-if="msg" class="alert alert-ok mt-16">{{ msg }}</div>
          <div v-if="err" class="alert alert-err mt-16">{{ err }}</div>
        </div>

        <div class="card">
          <div class="card-title">检索测试 <small>验证召回效果</small></div>
          <div class="row">
            <input class="input grow" v-model="query" placeholder="输入关键词或问题，例如「住宿费标准」"
                   @keyup.enter="search" />
            <button class="btn" @click="search" :disabled="searching">
              <icon name="search" :size="14" /> 检索
            </button>
          </div>
          <div v-if="results.length" class="mt-16" style="max-height:300px;overflow-y:auto">
            <div v-for="(r, i) in results" :key="i" class="list-item" style="display:block">
              <div class="row-between">
                <span style="font-size:13px;font-weight:500">{{ r.title }}</span>
                <span class="tag">{{ r.score }}</span>
              </div>
              <div class="tiny" style="margin-top:2px">{{ r.category }}<span v-if="r.heading"> · {{ r.heading }}</span></div>
              <div class="muted" style="font-size:12.5px;margin-top:4px">{{ r.snippet }}</div>
            </div>
          </div>
          <div v-else-if="searching" class="empty"><span class="spinner"></span></div>
          <div v-else class="empty">输入关键词试试检索效果</div>
        </div>
      </div>

      <div class="card mt-16">
        <div class="card-title">
          <span>已收录文档</span>
          <button class="btn btn-sm" @click="rebuild"><icon name="refresh" :size="13" /> 重建索引</button>
        </div>
        <div v-if="loading" class="empty"><span class="spinner"></span></div>
        <table v-else-if="docs.length" class="table">
          <thead>
            <tr><th>文档名称</th><th>类别</th><th>年份</th><th class="num">字数</th><th class="num">片段</th><th>导入时间</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="d in docs" :key="d.id">
              <td>{{ d.title }}<div class="tiny">{{ d.filename }} · {{ d.filetype }}</div></td>
              <td><span class="tag">{{ d.category }}</span></td>
              <td>{{ d.year || '—' }}</td>
              <td class="num">{{ fmt(d.char_count) }}</td>
              <td class="num">{{ d.chunk_count }}</td>
              <td class="tiny">{{ d.created_at }}</td>
              <td class="right"><button class="btn btn-ghost btn-sm" @click="remove(d)">删除</button></td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">还没有文档，上传一份试试</div>
      </div>
    </div>`,
  };

  /* ================================================================ 竞赛推荐 */
  const RecommendView = {
    data() {
      return {
        keyword: "",
        students: [],
        sno: "",
        student: null,
        interests: "",
        loading: false,
        result: null,
        err: "",
      };
    },
    mounted() {
      this.searchStudents();
    },
    methods: {
      async searchStudents() {
        try {
          const res = await API.students({ keyword: this.keyword, size: 20 });
          this.students = res.items;
        } catch (e) {
          /* ignore */
        }
      },
      pick(s) {
        this.sno = s.sno;
        this.student = s;
      },
      async run() {
        if (!this.sno) {
          this.err = "请先选择一名学生";
          return;
        }
        this.loading = true;
        this.err = "";
        this.result = null;
        try {
          this.result = await API.runWorkflow("recommend", { sno: this.sno, interests: this.interests });
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      tierClass(t) {
        return { 冲刺: "tag-danger", 稳妥: "tag-accent", 保底: "tag" }[t] || "tag";
      },
    },
    template: `
    <div>
      <div class="page-head">
        <h2>竞赛推荐</h2>
        <p>结合专业、年级、技术方向与往年参赛数据给出候选赛事。匹配度由规则加权计算，可逐项复核，不是模型随机生成。</p>
      </div>

      <div class="card">
        <div class="grid grid-3">
          <div class="field">
            <label>选择学生</label>
            <input class="input" v-model="keyword" placeholder="输入姓名/学号/专业搜索" @keyup.enter="searchStudents" />
            <div style="max-height:150px;overflow-y:auto;margin-top:6px">
              <div v-for="s in students" :key="s.sno" class="conv-item"
                   :class="{active: sno === s.sno}" @click="pick(s)">
                <span>{{ s.name }} · {{ s.sno }}</span>
                <span class="tiny">{{ s.grade_label }}</span>
              </div>
            </div>
          </div>
          <div class="field">
            <label>学生画像</label>
            <div style="border:1px solid var(--line);border-radius:9px;padding:12px;min-height:96px">
              <div v-if="student">
                <div style="font-weight:500">{{ student.name }}</div>
                <div class="tiny mt-8">{{ student.major }} · {{ student.grade_label }} · {{ student.class_name }}</div>
              </div>
              <div v-else class="tiny">尚未选择</div>
            </div>
          </div>
          <div class="field">
            <label>技术方向（逗号分隔，可空）</label>
            <input class="input" v-model="interests" placeholder="如：算法, 大模型, 嵌入式" />
            <button class="btn btn-primary mt-8" :disabled="loading || !sno" @click="run">
              {{ loading ? '分析中…' : '生成推荐' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="err" class="alert alert-err mt-16">{{ err }}</div>
      <div v-if="loading" class="card mt-16"><div class="empty"><span class="spinner"></span> 正在比对赛事库与历史数据</div></div>

      <div v-if="result" class="mt-16">
        <div class="card">
          <div class="card-title">
            <span>{{ result.data.student.name }} 的推荐结果</span>
            <small>{{ result.data.recommendations.length }} 项 · 用时 {{ result.duration_ms }} ms</small>
          </div>
          <div v-for="(r, i) in result.data.recommendations" :key="r.code" class="list-item" style="display:block">
            <div class="row" style="align-items:baseline">
              <span class="rank-no">{{ i + 1 }}</span>
              <span style="font-size:14px;font-weight:500">{{ r.name }}</span>
              <span class="tag">{{ r.level }}</span>
              <span class="tag" :class="tierClass(r.tier)">{{ r.tier }}</span>
              <span style="flex:1"></span>
              <span class="tiny">匹配度</span>
              <span class="mono" style="font-weight:600;font-size:15px">{{ r.score }}</span>
            </div>
            <div class="muted" style="font-size:12.5px;margin-top:6px;padding-left:32px">
              {{ r.llm_reason || (r.reasons || []).join('；') }}
            </div>
            <div class="tiny" style="margin-top:4px;padding-left:32px">
              往年 {{ r.history_teams }} 队参赛 / {{ r.history_awards }} 项获奖（{{ r.award_rate }}%）
              <span v-if="r.signup_end">　·　报名截止 {{ r.signup_end }}</span>
              <span v-if="r.prepare_weeks">　·　建议准备 {{ r.prepare_weeks }} 周</span>
            </div>
          </div>
        </div>

        <details class="card mt-16">
          <summary style="cursor:pointer;font-size:13.5px;font-weight:500">查看 Agent 执行轨迹</summary>
          <div class="trace-body mt-16">
            <div v-for="(t, i) in result.trace" :key="i" class="trace-node">
              <b>{{ t.node }}</b> · {{ t.description }} <span class="ms">{{ t.duration_ms }}ms</span>
            </div>
          </div>
        </details>
      </div>
    </div>`,
  };

  /* ================================================================ 备赛辅助 */
  const PrepView = {
    data() {
      return {
        competitions: [],
        competition: "",
        days: "",
        loading: false,
        result: null,
        err: "",
      };
    },
    mounted() {
      this.load();
    },
    methods: {
      async load() {
        try {
          const res = await API.competitions({});
          this.competitions = res.items;
          if (this.competitions.length) this.competition = this.competitions[0].name;
        } catch (e) {
          this.err = e.message;
        }
      },
      async run() {
        this.loading = true;
        this.err = "";
        this.result = null;
        try {
          this.result = await API.runWorkflow("prep", { competition: this.competition });
        } catch (e) {
          this.err = e.message;
        } finally {
          this.loading = false;
        }
      },
      md: renderMarkdown,
    },
    template: `
    <div>
      <div class="page-head">
        <h2>备赛辅助</h2>
        <p>依据赛事规程倒排备赛计划，输出时间安排、任务清单和材料准备清单。规程里的硬性要求会作为引用一并给出。</p>
      </div>

      <div class="card">
        <div class="grid grid-3">
          <div class="field" style="grid-column: span 2">
            <label>选择赛事</label>
            <select class="select" v-model="competition">
              <option v-for="c in competitions" :key="c.code" :value="c.name">
                {{ c.name }}（{{ c.level }} · {{ c.short_name }}）
              </option>
            </select>
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button class="btn btn-primary" :disabled="loading || !competition" @click="run">
              {{ loading ? '生成中…' : '生成备赛计划' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="err" class="alert alert-err mt-16">{{ err }}</div>
      <div v-if="loading" class="card mt-16"><div class="empty"><span class="spinner"></span> 正在检索规程并倒排计划</div></div>

      <div v-if="result" class="grid mt-16" style="grid-template-columns: 2fr 1fr">
        <div class="card">
          <div class="card-title">
            <span>备赛计划</span>
            <small v-if="result.data.days">距关键节点 {{ result.data.days }} 天</small>
          </div>
          <div class="md" v-html="md(result.answer)"></div>
        </div>

        <div class="card">
          <div class="card-title">规程依据</div>
          <div v-if="result.citations.length" class="col">
            <div v-for="(c, i) in result.citations" :key="i" class="cite">
              <div class="cite-head">
                <span class="cite-idx">{{ i + 1 }}</span>
                <span class="cite-title">{{ c.title }}</span>
              </div>
              <div class="cite-body">{{ c.snippet }}</div>
            </div>
          </div>
          <div v-else class="empty">未检索到规程原文</div>

          <div class="card-title mt-24">执行轨迹</div>
          <div class="trace-body">
            <div v-for="(t, i) in result.trace" :key="i" class="trace-node">
              <b>{{ t.node }}</b> <span class="ms">{{ t.duration_ms }}ms</span>
            </div>
          </div>
        </div>
      </div>
    </div>`,
  };

  window.Views = Object.assign(window.Views || {}, {
    ChatView,
    KnowledgeView,
    RecommendView,
    PrepView,
  });
})();
