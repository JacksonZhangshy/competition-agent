"""样例数据生成：赛事、届次、师生、参赛项目、获奖记录。

数据用于系统演示与测试，接入学院真实台账时替换本脚本或直接导入 Excel。
所有随机过程使用固定种子，保证每次生成结果一致、可复现。
"""
from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import db_session, init_db  # noqa: E402
from backend.models import (  # noqa: E402
    BudgetRequest,
    Competition,
    Edition,
    LoanRequest,
    Reimbursement,
    Student,
    SystemConfig,
    Team,
    TeamMember,
    Teacher,
)
from backend.services.budget import DEFAULT_RULES  # noqa: E402

RNG = random.Random(20261115)

MAJORS = [
    "计算机科学与技术",
    "软件工程",
    "人工智能",
    "数据科学与大数据技术",
    "网络工程",
    "物联网工程",
]

# 专业 → 学院 对照，可按实际院系调整
COLLEGE_OF_MAJOR = {
    "计算机科学与技术": "计算与智能技术学院",
    "软件工程": "计算与智能技术学院",
    "人工智能": "计算与智能技术学院",
    "数据科学与大数据技术": "计算与智能技术学院",
    "网络工程": "信息与通信工程学院",
    "物联网工程": "信息与通信工程学院",
}

SURNAMES = "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
GIVEN = "伟芳娜秀英敏静丽强磊洋艳勇军杰娟涛明超秀霞平刚桂英欣怡子豪雨涵思远嘉怡"

COMPETITIONS = [
    {
        "code": "IEC",
        "name": "中国国际大学生创新大赛",
        "short_name": "国创赛",
        "level": "国家级",
        "category": "创新创业",
        "organizer": "教育部",
        "majors": "计算机科学与技术,软件工程,人工智能,数据科学与大数据技术",
        "grades": "2,3,4",
        "difficulty": 5,
        "workload": 5,
        "tags": "创新创业,商业计划,项目孵化",
        "description": "原“互联网+”大学生创新创业大赛，采用校赛—省赛—国赛三级赛制，分高教主赛道、青年红色筑梦之旅赛道、产业命题赛道。",
    },
    {
        "code": "CHALLENGE",
        "name": "“挑战杯”全国大学生课外学术科技作品竞赛",
        "short_name": "挑战杯",
        "level": "国家级",
        "category": "学科竞赛",
        "organizer": "共青团中央、中国科协、教育部",
        "majors": "计算机科学与技术,软件工程,人工智能,网络工程,物联网工程",
        "grades": "2,3,4",
        "difficulty": 5,
        "workload": 5,
        "tags": "学术科技,发明制作,社会调查",
        "description": "两年一届，作品分自然科学类学术论文、哲学社会科学类社会调查报告、科技发明制作三类。",
    },
    {
        "code": "ACM",
        "name": "ACM-ICPC 国际大学生程序设计竞赛",
        "short_name": "ACM/ICPC",
        "level": "国家级",
        "category": "程序设计",
        "organizer": "ICPC 亚洲区组委会",
        "majors": "计算机科学与技术,软件工程,人工智能",
        "grades": "1,2,3,4",
        "difficulty": 5,
        "workload": 5,
        "tags": "算法,程序设计,团队赛",
        "description": "三人一队、一台电脑、五小时解决 8-13 道算法题，按解题数与罚时排名。",
    },
    {
        "code": "LANQIAO",
        "name": "蓝桥杯全国软件和信息技术专业人才大赛",
        "short_name": "蓝桥杯",
        "level": "国家级",
        "category": "程序设计",
        "organizer": "工业和信息化部人才交流中心",
        "majors": "计算机科学与技术,软件工程,人工智能,数据科学与大数据技术,物联网工程",
        "grades": "1,2,3,4",
        "difficulty": 3,
        "workload": 3,
        "tags": "算法,Java,Python,C++,单片机",
        "description": "个人赛为主，设软件类、电子类、数字科技创新赛等赛道，省赛—国赛两级。",
    },
    {
        "code": "CUMCM",
        "name": "全国大学生数学建模竞赛",
        "short_name": "数学建模",
        "level": "国家级",
        "category": "数学建模",
        "organizer": "中国工业与应用数学学会",
        "majors": "计算机科学与技术,数据科学与大数据技术,人工智能,软件工程",
        "grades": "2,3,4",
        "difficulty": 4,
        "workload": 4,
        "tags": "数学建模,论文写作,数据分析",
        "description": "三人一队，72 小时完成一道实际问题的建模、求解与论文写作。",
    },
    {
        "code": "NUEDC",
        "name": "全国大学生电子设计竞赛",
        "short_name": "电子设计",
        "level": "国家级",
        "category": "电子设计",
        "organizer": "教育部高等教育司",
        "majors": "物联网工程,计算机科学与技术",
        "grades": "2,3,4",
        "difficulty": 5,
        "workload": 5,
        "tags": "硬件,嵌入式,电路设计",
        "description": "四天三夜封闭完成指定题目，含方案设计、硬件制作、软件编程与测试报告。",
    },
    {
        "code": "C4",
        "name": "中国大学生计算机设计大赛",
        "short_name": "计设赛",
        "level": "国家级",
        "category": "学科竞赛",
        "organizer": "教育部高等学校计算机类专业教学指导委员会",
        "majors": "计算机科学与技术,软件工程,人工智能,数据科学与大数据技术",
        "grades": "1,2,3,4",
        "difficulty": 3,
        "workload": 3,
        "tags": "软件开发,数字媒体,人工智能应用",
        "description": "按作品类别分组，涵盖软件应用与开发、数媒设计、人工智能应用等大类。",
    },
    {
        "code": "SERVICE",
        "name": "中国大学生服务外包创新创业大赛",
        "short_name": "服务外包",
        "level": "国家级",
        "category": "创新创业",
        "organizer": "教育部、商务部",
        "majors": "软件工程,计算机科学与技术,数据科学与大数据技术",
        "grades": "2,3,4",
        "difficulty": 3,
        "workload": 3,
        "tags": "企业命题,软件开发,项目管理",
        "description": "分企业命题赛道与创业实践赛道，强调工程化交付与商业可行性。",
    },
    {
        "code": "BIGDATA",
        "name": "全国大学生大数据挑战赛",
        "short_name": "大数据挑战赛",
        "level": "行业级",
        "category": "学科竞赛",
        "organizer": "中国计算机学会",
        "majors": "数据科学与大数据技术,人工智能,计算机科学与技术",
        "grades": "2,3,4",
        "difficulty": 4,
        "workload": 3,
        "tags": "数据挖掘,机器学习,竞赛平台",
        "description": "线上算法赛，基于真实业务数据完成预测任务，按排行榜评分。",
    },
    {
        "code": "AIAPP",
        "name": "中国高校计算机大赛—人工智能创意赛",
        "short_name": "AI创意赛",
        "level": "国家级",
        "category": "学科竞赛",
        "organizer": "教育部高等学校计算机类专业教学指导委员会",
        "majors": "人工智能,计算机科学与技术,软件工程,数据科学与大数据技术",
        "grades": "2,3,4",
        "difficulty": 4,
        "workload": 4,
        "tags": "人工智能,大模型,应用创新",
        "description": "面向真实场景的 AI 应用创新，提交方案、原型与技术报告。",
    },
    {
        "code": "CTF",
        "name": "全国大学生信息安全竞赛",
        "short_name": "信安竞赛",
        "level": "国家级",
        "category": "学科竞赛",
        "organizer": "教育部高等学校网络空间安全专业教学指导委员会",
        "majors": "网络工程,计算机科学与技术",
        "grades": "2,3,4",
        "difficulty": 5,
        "workload": 4,
        "tags": "网络安全,CTF,渗透测试",
        "description": "含作品赛与技能赛（CTF），技能赛采用解题与攻防对抗形式。",
    },
    {
        "code": "IOT",
        "name": "全国大学生物联网设计竞赛",
        "short_name": "物联网设计",
        "level": "国家级",
        "category": "电子设计",
        "organizer": "教育部高等学校计算机类专业教学指导委员会",
        "majors": "物联网工程,计算机科学与技术,网络工程",
        "grades": "2,3,4",
        "difficulty": 4,
        "workload": 4,
        "tags": "物联网,传感器,边缘计算",
        "description": "基于指定平台完成物联网系统设计与实现，强调软硬件协同。",
    },
    {
        "code": "LADDER",
        "name": "中国高校计算机大赛—团体程序设计天梯赛",
        "short_name": "天梯赛",
        "level": "国家级",
        "category": "程序设计",
        "organizer": "教育部高等学校计算机类专业教学指导委员会",
        "majors": "计算机科学与技术,软件工程,人工智能",
        "grades": "1,2,3,4",
        "difficulty": 4,
        "workload": 3,
        "tags": "程序设计,团队赛,算法",
        "description": "十人一队，按题目难度梯度计分，强调团队整体水平。",
    },
    {
        "code": "NECCS",
        "name": "全国大学生英语竞赛",
        "short_name": "英语竞赛",
        "level": "国家级",
        "category": "外语",
        "organizer": "高等学校大学外语教学研究会",
        "majors": "",
        "grades": "1,2,3,4",
        "difficulty": 2,
        "workload": 2,
        "tags": "英语,听力,写作",
        "description": "分 A/B/C/D 四类，C 类面向非英语专业本科生，含听力、词汇、阅读、翻译、写作。",
    },
    {
        "code": "PROVINC",  # 校级赛事示例
        "name": "校级程序设计新生赛",
        "short_name": "新生赛",
        "level": "校级",
        "category": "程序设计",
        "organizer": "计算与智能技术学院",
        "majors": "计算机科学与技术,软件工程,人工智能,数据科学与大数据技术,网络工程,物联网工程",
        "grades": "1,2",
        "difficulty": 2,
        "workload": 2,
        "tags": "新生,程序设计,入门",
        "description": "面向大一、大二学生的入门级程序设计竞赛，为省级以上赛事选拔苗子。",
    },
]

RULES_TEMPLATE = {
    "eligibility": ["全日制在校本科生", "每人限报 1 项", "团队赛人数 3-5 人", "需有指导教师 1-2 名"],
    "materials": ["报名表", "参赛作品说明", "原创性声明", "指导教师推荐意见"],
    "award": ["一等奖 10%", "二等奖 20%", "三等奖 30%"],
    "schedule": ["校级选拔", "省级复赛", "全国决赛"],
}


def _rand_name() -> str:
    return RNG.choice(SURNAMES) + "".join(RNG.choice(GIVEN) for _ in range(RNG.choice([1, 2])))


def seed_students() -> list[Student]:
    students: list[Student] = []
    idx = 0
    # 只保留在读年级：入学年份 = 今年-3 … 今年（大一到大四），避免出现“大五”
    grades = [dt.date.today().year - i for i in (3, 2, 1, 0)]
    for major_i, major in enumerate(MAJORS):
        for grade in grades:
            for k in range(6):
                idx += 1
                sno = f"{grade}{major_i + 1:02d}{k + 1:02d}"
                students.append(
                    Student(
                        sno=sno,
                        name=_rand_name(),
                        gender=RNG.choice(["男", "男", "女"]),
                        college=COLLEGE_OF_MAJOR.get(major, ""),
                        major=major,
                        grade=grade,
                        class_name=f"{major[:2]}{str(grade)[2:]}-{k // 3 + 1}班",
                        phone=f"13{RNG.randint(100000000, 999999999)}",
                        email=f"{sno}@stu.edu.cn",
                    )
                )
    return students


def seed_teachers() -> list[Teacher]:
    titles = ["教授", "副教授", "副教授", "讲师", "讲师"]
    return [
        Teacher(
            tno=f"T{1000 + i}",
            name=_rand_name(),
            title=RNG.choice(titles),
            dept="计算与智能技术学院",
            phone=f"13{RNG.randint(100000000, 999999999)}",
            email=f"t{1000 + i}@edu.cn",
        )
        for i in range(22)
    ]


def seed_competitions(years: list[int]) -> tuple[list[Competition], list[Edition]]:
    comps: list[Competition] = []
    editions: list[Edition] = []
    for c in COMPETITIONS:
        comp = Competition(**c, official_url=f"https://example.edu.cn/competition/{c['code'].lower()}", is_active=True)
        comps.append(comp)

    return comps, editions


def _edition_plans(comp: Competition, today: dt.date) -> list[dict]:
    """安排该赛事的赛季：近 4 年历史 + 本年度 + 下一届。

    “下一届”的存在很关键——如果所有赛季都已截止，推荐结果会全是「已截止」，
    备赛计划也找不到可倒排的截止日，演示时看起来像数据坏了。
    """
    td = dt.timedelta
    plans: list[dict] = []

    def skip(year: int) -> bool:
        return comp.code == "CHALLENGE" and year % 2 == 1  # 挑战杯两年一届

    for year in range(today.year - 4, today.year):
        if skip(year):
            continue
        se = dt.date(year, RNG.randint(3, 5), RNG.randint(10, 28))
        plans.append(
            {
                "year": year,
                "signup_start": se - td(RNG.randint(20, 40)),
                "signup_end": se,
                "contest_start": se + td(RNG.randint(20, 45)),
                "status": "已结束",
                "live": False,
            }
        )

    if not skip(today.year):
        se = today - td(RNG.randint(40, 150))
        plans.append(
            {
                "year": today.year,
                "signup_start": se - td(RNG.randint(20, 40)),
                "signup_end": se,
                "contest_start": se + td(RNG.randint(20, 45)),
                "status": "已结束",
                "live": False,
            }
        )

    next_year = today.year + 1
    if not skip(next_year):
        ss = today - td(5)
        se = today + td(RNG.randint(22, 40))
        plans.append(
            {
                "year": next_year,
                "signup_start": ss,
                "signup_end": se,
                "contest_start": se + td(RNG.randint(25, 45)),
                "status": "报名中",
                "live": True,
            }
        )
    return plans


def seed_teams(comps: list[Competition], students: list[Student], teachers: list[Teacher]) -> int:
    today = dt.date.today()
    count = 0
    with db_session() as db:
        db.add(SystemConfig(key="budget_rules", value=DEFAULT_RULES, remark="经费开支标准"))
        db.add(
            SystemConfig(
                key="recommend_weights",
                value={"major": 25, "grade": 12, "time": 8, "history": -8, "difficulty": -12, "award_rate": 6},
                remark="竞赛推荐打分权重",
            )
        )
        db.commit()

    project_prefixes = [
        "基于深度学习的", "面向校园场景的", "多模态融合的", "轻量化边缘计算的",
        "面向竞赛训练的", "基于大模型的", "面向工业质检的", "可解释的",
    ]
    project_subjects = [
        "智能问答系统", "图像识别平台", "数据分析工具", "推荐算法研究",
        "物联网监测终端", "安全检测系统", "可视化决策平台", "自动化测试框架",
        "知识图谱构建", "语音交互助手",
    ]

    with db_session() as db:
        for c in comps:
            db.add(c)
        db.flush()

        bud_seq = 0
        for comp in comps:
            for plan in _edition_plans(comp, today):
                year = plan["year"]
                live = plan["live"]
                seq = year - (today.year - 5)
                signup_start = plan["signup_start"]
                signup_end = plan["signup_end"]
                contest_start = plan["contest_start"]
                status = plan["status"]
                edition = Edition(
                    competition_id=comp.id,
                    year=year,
                    seq=seq,
                    notice_title=f"关于举办{year}年{comp.name}的通知",
                    signup_start=signup_start,
                    signup_end=signup_end,
                    contest_start=contest_start,
                    contest_end=contest_start + dt.timedelta(days=RNG.randint(1, 4)),
                    fee={"国家级": 300.0, "省级": 200.0, "校级": 0.0, "行业级": 0.0}[comp.level],
                    venue={"国家级": "另行通知", "省级": "省会城市", "校级": "校内", "行业级": "线上"}[comp.level],
                    status=status,
                    rules_json={
                        **RULES_TEMPLATE,
                        "award": [f"一等奖 10%（约 {RNG.randint(2, 6)} 项）", "二等奖 20%", "三等奖 30%"],
                        "schedule": ["校级选拔（4 月）", "省级复赛（5-6 月）", "全国决赛（7-8 月）"]
                        if comp.level == "国家级"
                        else ["校内报名（4 月）", "校级评审（5 月）"],
                    },
                )
                db.add(edition)
                db.flush()

                n_teams = RNG.randint(2, 7) if comp.level != "校级" else RNG.randint(3, 6)
                if comp.code in {"ACM", "LANQIAO", "LADDER"}:
                    n_teams += 2
                if live:
                    n_teams = max(2, n_teams // 2)  # 新赛季刚开放报名，队伍还不多

                for _ in range(n_teams):
                    leader = RNG.choice(students)
                    teacher = RNG.choice(teachers)
                    project = f"{RNG.choice(project_prefixes)}{RNG.choice(project_subjects)}"

                    award_rate = {"国家级": 0.42, "省级": 0.55, "校级": 0.65, "行业级": 0.45}[comp.level]
                    won = (not live) and RNG.random() < award_rate
                    award_grade = "无"
                    award_level = "无"
                    if won:
                        award_grade = comp.level if comp.level in {"国家级", "省级", "校级"} else "国家级"
                        if RNG.random() < 0.12 and comp.level == "国家级":
                            award_grade = "省级"
                        award_level = RNG.choices(
                            ["特等奖", "一等奖", "二等奖", "三等奖", "优秀奖"],
                            weights=[3, 15, 27, 35, 20],
                        )[0]

                    team = Team(
                        edition_id=edition.id,
                        project_name=project,
                        leader_student_id=leader.id,
                        teacher_id=teacher.id,
                        status="备赛" if live else ("获奖" if won else "参赛"),
                        award_grade=award_grade,
                        award_level=award_level,
                        signup_date=min(today, signup_end) - dt.timedelta(days=RNG.randint(0, 6)),
                        finish_date=None if live else contest_start,
                        budget_total=round(RNG.uniform(1500, 9000), 2) if comp.level != "校级" else round(RNG.uniform(0, 1200), 2),
                        remark="",
                    )
                    db.add(team)
                    db.flush()
                    count += 1

                    members = RNG.sample(students, k=RNG.randint(1, 3))
                    db.add(TeamMember(team_id=team.id, student_id=leader.id, role="负责人"))
                    for m in members:
                        if m.id != leader.id:
                            db.add(TeamMember(team_id=team.id, student_id=m.id, role="成员"))

                # 部分队伍生成预算单
                if year >= today.year - 1 and comp.level != "校级":
                    t = db.query(Team).filter(Team.edition_id == edition.id).first()
                    if t:
                        bud_seq += 1
                        db.add(
                            BudgetRequest(
                                budget_no=f"BUD{year}{bud_seq:04d}",
                                team_id=t.id,
                                title=f"{comp.name}参赛经费预算",
                                items=[
                                    {"name": "报名费", "spec": "参赛报名费", "unit": "队", "qty": 1, "price": edition.fee, "amount": edition.fee, "note": "", "category": "报名费"},
                                    {"name": "交通费", "spec": "往返", "unit": "人·次", "qty": 3, "price": 700.0, "amount": 2100.0, "note": "", "category": "差旅费"},
                                    {"name": "住宿费", "spec": "3 人 × 2 晚", "unit": "人·天", "qty": 6, "price": 380.0, "amount": 2280.0, "note": "", "category": "住宿费"},
                                ],
                                total=round(edition.fee + 4380, 2),
                                approved_amount=round(edition.fee + 4380, 2),
                                applicant=t.leader.name if t.leader else "",
                                status="已提交" if live else "已批准",
                            )
                        )
    return count


def seed_all(force: bool = False) -> dict:
    init_db()
    with db_session() as db:
        existing = db.query(Competition).count()
        if existing > 0 and not force:
            return {"skipped": True, "competitions": existing, "message": "已存在数据，跳过"}

        if force:
            # 必须按外键依赖倒序删除，否则先删 team 会触发 FK 约束失败
            for model in (
                Reimbursement, LoanRequest, BudgetRequest,
                TeamMember, Team, Edition, Competition,
                Student, Teacher, SystemConfig,
            ):
                db.query(model).delete()
            db.commit()

    students = seed_students()
    teachers = seed_teachers()
    with db_session() as db:
        db.add_all(students)
        db.add_all(teachers)
        db.commit()

    with db_session() as db:
        students = db.query(Student).all()
        teachers = db.query(Teacher).all()

    comps, _ = seed_competitions([])
    team_count = seed_teams(comps, students, teachers)

    with db_session() as db:
        return {
            "students": db.query(Student).count(),
            "teachers": db.query(Teacher).count(),
            "competitions": db.query(Competition).count(),
            "editions": db.query(Edition).count(),
            "teams": db.query(Team).count(),
            "awards": db.query(Team).filter(Team.award_level != "无").count(),
        }


if __name__ == "__main__":
    force = "--force" in sys.argv
    info = seed_all(force=force)
    print("样例数据生成完成：")
    for k, v in info.items():
        print(f"  {k:14s} {v}")
