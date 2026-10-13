# -*- coding: utf-8 -*-
"""
动作名 / 行为名 三语对照表
Action & behaviour name dictionary (Japanese / Chinese / English)
==============================================================================
配置里的动作名沿用原版日文（保证 100% 兼容），本表提供中文与英文显示名。

Action names in the configuration stay in Japanese (full compatibility with the
original XML); this table supplies Chinese and English display names.
"""

from __future__ import annotations

__all__ = ["ACTION_NAMES", "KIND_NAMES", "FRAME_NAMES", "display_name", "ALL_KNOWN"]

#: 日文原名 -> (中文, English) / Japanese -> (Chinese, English)
ACTION_NAMES: dict[str, tuple[str, str]] = {
    # --- 基础动作 / basic ---
    "振り向く":                 ("转身", "Turn Around"),
    "変位":                     ("位移", "Offset"),
    "立つ":                     ("站立", "Stand"),
    "歩く":                     ("走路", "Walk"),
    "走る":                     ("奔跑", "Run"),
    "猛ダッシュ":               ("猛冲", "Dash"),
    # --- 坐姿系 / sitting ---
    "座る":                     ("坐下", "Sit"),
    "座って見上げる":           ("坐着抬头看", "Sit and Look Up"),
    "座ってマウスを見上げる":   ("坐着看鼠标", "Sit and Look Up at Cursor"),
    "座って首が回る":           ("坐着转头", "Sit and Turn Head"),
    "楽に座る":                 ("放松地坐", "Sit Relaxed"),
    "足を下ろして座る":         ("放下腿坐", "Sit with Legs Down"),
    "足をぶらぶらさせる":       ("晃腿", "Swing Legs"),
    # --- 趴卧系 / lying ---
    "寝そべる":                 ("趴下", "Lie Down"),
    "ずりずり":                 ("蹭着挪动", "Slide Along"),
    # --- 天花板系 / ceiling ---
    "天井に掴まる":             ("抓住天花板", "Grab Ceiling"),
    "天井を伝う":               ("沿天花板移动", "Move Along Ceiling"),
    # --- 墙壁系 / wall ---
    "壁に掴まる":               ("抓住墙壁", "Grab Wall"),
    "壁を登る":                 ("爬墙", "Climb Wall"),
    # --- 窗口(IE)系 / window ---
    "IEを持って落ちる":         ("抓着窗口下落", "Fall Holding Window"),
    "IEを持って歩く":           ("抓着窗口走", "Walk Holding Window"),
    "IEを持って走る":           ("抓着窗口跑", "Run Holding Window"),
    "IEを投げる":               ("扔出窗口", "Throw Window"),
    # --- 物理系 / physics ---
    "ジャンプ":                 ("跳跃", "Jump"),
    "落ちる":                   ("下落", "Fall"),
    "跳ねる":                   ("弹跳", "Bounce"),
    "転ぶ":                     ("摔倒", "Tumble"),
    "つままれる":               ("被捏住", "Dragged"),
    "抵抗する":                 ("挣扎", "Struggle"),
    # --- 系统行为 / system ---
    "落下する":                 ("坠落", "Falling"),
    "ドラッグされる":           ("被拖拽", "Being Dragged"),
    "投げられる":               ("被抛出", "Being Thrown"),
    "立ってボーっとする":       ("站着发呆", "Stand Dazed"),
    "座ってボーっとする":       ("坐着发呆", "Sit Dazed"),
    "寝そべってボーっとする":   ("趴着发呆", "Lie Dazed"),
    "座って足をぶらぶらさせる": ("坐着晃腿", "Sit and Swing Legs"),
    "壁に掴まってボーっとする": ("抓墙发呆", "Dazed on Wall"),
    "壁から落ちる":             ("从墙上掉下", "Fall from Wall"),
    "天井に掴まってボーっとする": ("抓天花板发呆", "Dazed on Ceiling"),
    "天井から落ちる":           ("从天花板掉下", "Fall from Ceiling"),
    # --- 屏幕底边 / screen bottom edge ---
    "ワークエリアの下辺を歩く":                     ("沿屏幕底边走", "Walk along Bottom"),
    "ワークエリアの下辺を走る":                     ("沿屏幕底边跑", "Run along Bottom"),
    "ワークエリアの下辺でずりずり":                 ("沿屏幕底边蹭动", "Slide along Bottom"),
    "ワークエリアの下辺の左の端っこで座る":         ("走到左下角坐下", "Sit at Bottom-Left"),
    "ワークエリアの下辺の右の端っこで座る":         ("走到右下角坐下", "Sit at Bottom-Right"),
    "ワークエリアの下辺から左の壁によじのぼる":     ("从底边爬左墙", "Climb Left Wall from Bottom"),
    "ワークエリアの下辺から右の壁によじのぼる":     ("从底边爬右墙", "Climb Right Wall from Bottom"),
    "走ってワークエリアの下辺の左の端っこで座る":   ("跑到左下角坐下", "Run to Bottom-Left and Sit"),
    "走ってワークエリアの下辺の右の端っこで座る":   ("跑到右下角坐下", "Run to Bottom-Right and Sit"),
    "走ってワークエリアの下辺から左の壁によじのぼる": ("跑到左墙攀爬", "Run to Left Wall and Climb"),
    "走ってワークエリアの下辺から右の壁によじのぼる": ("跑到右墙攀爬", "Run to Right Wall and Climb"),
    # --- 屏幕墙 / screen walls ---
    "ワークエリアの壁を途中まで登る": ("爬墙到一半", "Climb Wall Halfway"),
    "ワークエリアの壁を登る":         ("爬上屏幕边墙", "Climb Screen Wall"),
    "ワークエリアの上辺を伝う":       ("沿屏幕上边移动", "Move along Top"),
    "左の壁に飛びつく":               ("扑向左墙", "Jump to Left Wall"),
    "右の壁に飛びつく":               ("扑向右墙", "Jump to Right Wall"),
    # --- 窗口顶部 / window top ---
    "IEの天井を歩く":                             ("在窗口顶部走", "Walk on Window Top"),
    "IEの天井を走る":                             ("在窗口顶部跑", "Run on Window Top"),
    "IEの天井でずりずり":                         ("在窗口顶部蹭动", "Slide on Window Top"),
    "IEの天井の左の端っこで座る":                 ("在窗口顶部左端坐下", "Sit at Window Top-Left"),
    "IEの天井の右の端っこで座る":                 ("在窗口顶部右端坐下", "Sit at Window Top-Right"),
    "IEの天井の左の端っこから飛び降りる":         ("从窗口顶部左端跳下", "Jump off Window Top-Left"),
    "IEの天井の右の端っこから飛び降りる":         ("从窗口顶部右端跳下", "Jump off Window Top-Right"),
    "走ってIEの天井の左の端っこで座る":           ("跑到窗口顶左端坐下", "Run to Window Top-Left and Sit"),
    "走ってIEの天井の右の端っこで座る":           ("跑到窗口顶右端坐下", "Run to Window Top-Right and Sit"),
    "走ってIEの天井の左の端っこから飛び降りる":   ("跑到窗口顶左端跳下", "Run off Window Top-Left"),
    "走ってIEの天井の右の端っこから飛び降りる":   ("跑到窗口顶右端跳下", "Run off Window Top-Right"),
    "猛ダッシュでIEの天井の左の端っこから飛び降りる": ("冲刺从窗口顶左端跳下", "Dash off Window Top-Left"),
    "猛ダッシュでIEの天井の右の端っこから飛び降りる": ("冲刺从窗口顶右端跳下", "Dash off Window Top-Right"),
    # --- 窗口侧壁与下边 / window sides and bottom ---
    "IEの壁を途中まで登る":             ("爬窗口侧壁到一半", "Climb Window Side Halfway"),
    "IEの壁を登る":                     ("爬上窗口侧壁", "Climb Window Side"),
    "IEの下辺を伝う":                   ("沿窗口下边移动", "Move along Window Bottom"),
    "IEの下辺から左の壁によじのぼる":   ("从窗口下边爬左壁", "Climb Left Wall from Window Bottom"),
    "IEの下辺から右の壁によじのぼる":   ("从窗口下边爬右壁", "Climb Right Wall from Window Bottom"),
    "IEの下に飛びつく":                 ("扑到窗口下方", "Jump under Window"),
    "IEの左に飛びつく":                 ("扑到窗口左侧", "Jump to Window Left"),
    "IEの右に飛びつく":                 ("扑到窗口右侧", "Jump to Window Right"),
    "IEを右に投げる":                   ("向右扔窗口", "Throw Window Right"),
    "IEを左に投げる":                   ("向左扔窗口", "Throw Window Left"),
    "走ってIEを右に投げる":             ("跑过去向右扔窗口", "Run and Throw Window Right"),
    "走ってIEを左に投げる":             ("跑过去向左扔窗口", "Run and Throw Window Left"),
    # --- 鼠标相关 / cursor ---
    "マウスの周りに集まる":                 ("聚集到鼠标周围", "Gather around Cursor"),
    "座ってマウスのほうを見る":             ("坐着朝鼠标看", "Sit and Look at Cursor"),
    "座ってマウスのほうを見てたら首が回った": ("坐着看鼠标时转头", "Sit at Cursor, Head Turns"),
    # --- 增殖 / breeding ---
    "引っこ抜く1":       ("拔萝卜 1", "Pull Out 1"),
    "引っこ抜く2":       ("拔萝卜 2", "Pull Out 2"),
    "引っこ抜く":        ("拔萝卜", "Breed by Pulling"),
    "引っこ抜かれる":    ("被拔出", "Being Pulled Out"),
    "分裂1":             ("分裂 1", "Split 1"),
    "分裂する":          ("分裂", "Split"),
    "分裂した":          ("分裂完成", "Newly Split"),
}

#: 动作种类 / action kinds
KIND_NAMES: dict[str, tuple[str, str]] = {
    "stay":      ("静止", "Stay"),
    "move":      ("移动", "Move"),
    "fixed":     ("固定", "Fixed"),
    "composite": ("复合", "Composite"),
    "select":    ("选择", "Select"),
    "builtin":   ("内建", "Built-in"),
}

#: 锚框 / anchor frames
FRAME_NAMES: dict[str, tuple[str, str]] = {
    "ground":  ("地面", "Ground"),
    "wall":    ("墙壁", "Wall"),
    "ceiling": ("天花板", "Ceiling"),
    "":        ("无", "None"),
}

ALL_KNOWN = set(ACTION_NAMES)


def display_name(ja: str, lang: str = "zh_CN", bilingual: bool = True) -> str:
    """
    取得显示名 / Build a display name for an action or behaviour.

    bilingual=True 时返回「中文 English」双语形式。
    With *bilingual* the result looks like "中文 English".
    """
    if not ja:
        return ""
    zh, en = ACTION_NAMES.get(ja, (ja, ja))
    if lang.startswith("ja"):
        return ja if not bilingual else "%s" % ja
    if lang.startswith("en"):
        return "%s %s" % (en, zh) if bilingual else en
    return "%s %s" % (zh, en) if bilingual else zh
