# 导入类型注解模块，Optional表示变量可以是指定类型或None
from typing import Optional
# 导入操作系统相关模块，用于读取环境变量
import os
# 导入requests库，用于发送HTTP请求（查天气）
import requests
# 导入dotenv库，用于加载.env文件中的环境变量
from dotenv import load_dotenv
try:
    # 尝试从langchain_core.tools导入tool装饰器（用于定义Agent工具）
    from langchain_core.tools import tool
except ImportError:
    # 导入失败时的降级处理（兼容不同版本）
    from langchain_core.tools import tool

# 加载.env文件中的环境变量（比如高德API密钥）
load_dotenv()

# 从环境变量读取高德天气API地址
AMAP_WEATHER_API = os.getenv("AMAP_WEATHER_API")
# 从环境变量读取高德API密钥
AMAP_API_KEY = os.getenv("AMAP_API_KEY")

# 全局变量：存储最近一次RAG（知识库检索）的上下文，初始为None
_LAST_RAG_CONTEXT = None
# 全局变量：统计本轮对话中知识库工具的调用次数，防止重复调用
_KNOWLEDGE_TOOL_CALLS_THIS_TURN = 0
# 全局变量：RAG步骤队列（用于流式返回检索过程），由Agent初始化
_RAG_STEP_QUEUE = None  # asyncio.Queue类型
# 全局变量：事件循环（用于跨线程调度RAG步骤）
_RAG_STEP_LOOP = None   # asyncio loop对象


def _set_last_rag_context(context: dict):
    """
    私有函数：设置最近一次RAG检索的上下文
    :param context: 字典类型，存储RAG检索的追踪信息
    """
    # 使用global声明修改全局变量
    global _LAST_RAG_CONTEXT
    _LAST_RAG_CONTEXT = context


def get_last_rag_context(clear: bool = True) -> Optional[dict]:
    """
    公共函数：获取最近一次RAG检索上下文，默认读取后清空（避免跨请求污染）
    :param clear: 是否清空上下文，默认True
    :return: RAG上下文字典（None表示无）
    """
    global _LAST_RAG_CONTEXT
    # 先把当前上下文赋值给临时变量
    context = _LAST_RAG_CONTEXT
    # 如果需要清空，就把全局变量置为None
    if clear:
        _LAST_RAG_CONTEXT = None
    # 返回上下文
    return context


def reset_tool_call_guards():
    """
    公共函数：每轮对话开始时重置工具调用计数（防止本轮重复调用知识库工具）
    """
    global _KNOWLEDGE_TOOL_CALLS_THIS_TURN
    # 重置为0
    _KNOWLEDGE_TOOL_CALLS_THIS_TURN = 0


def set_rag_step_queue(queue):
    """
    公共函数：设置RAG步骤队列，并捕获当前事件循环（用于跨线程推送检索步骤）
    :param queue: asyncio.Queue对象，用于存储RAG步骤
    """
    global _RAG_STEP_QUEUE, _RAG_STEP_LOOP
    # 赋值队列
    _RAG_STEP_QUEUE = queue
    if queue:
        # 如果队列不为空，导入asyncio模块
        import asyncio
        try:
            # 获取当前正在运行的事件循环（主线程）
            _RAG_STEP_LOOP = asyncio.get_running_loop()
        except RuntimeError:
            # 如果没有运行中的循环，获取默认循环
            _RAG_STEP_LOOP = asyncio.get_event_loop()
    else:
        # 队列为空时，循环也置为None
        _RAG_STEP_LOOP = None


def emit_rag_step(icon: str, label: str, detail: str = ""):
    """
    公共函数：向队列发送一个RAG检索步骤（支持跨线程安全调用）
    用于流式返回时，实时展示检索过程（比如“正在检索知识库”、“找到3条相关文档”）
    :param icon: 步骤图标标识（前端展示用）
    :param label: 步骤标题（比如“检索中”）
    :param detail: 步骤详情（比如“匹配关键词：Python”）
    """
    global _RAG_STEP_QUEUE, _RAG_STEP_LOOP
    # 只有队列和循环都存在时才发送
    if _RAG_STEP_QUEUE is not None and _RAG_STEP_LOOP is not None:
        # 构造步骤字典
        step = {"icon": icon, "label": label, "detail": detail}
        try:
            # 检查循环是否关闭
            if not _RAG_STEP_LOOP.is_closed():
                # 跨线程安全地把步骤放入队列（避免线程冲突）
                _RAG_STEP_LOOP.call_soon_threadsafe(_RAG_STEP_QUEUE.put_nowait, step)
        except Exception:
            # 捕获所有异常，避免工具调用失败导致整体崩溃
            pass


@tool("get_current_weather")
def get_current_weather(location: str, extensions: str = "base") -> str:
    """
    Agent工具：根据城市名查询当前天气
    :param location: 要查询的城市名称，例如"北京"、"上海"、"杭州"、"Shenzhen"
    :param extensions: 查询类型，可选值："base"（实时天气，默认）或 "all"（天气预报）
    :return: 格式化的天气信息字符串
    """
    import requests

    if not location:
        return "location 参数不能为空"

    try:
        # wttr.in 是免费天气服务，不需要 API key
        # 用 format=j1 返回结构化 JSON，format=3 返回简短文本
        url = f"https://wttr.in/{location}?format=j1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "curl/8.0"})
        resp.raise_for_status()
        data = resp.json()

        if not data.get("current_condition"):
            return f"未查询到 {location} 的天气数据，请检查城市名是否正确"

        c = data["current_condition"][0]
        area = (data.get("nearest_area") or [{}])[0]
        city = area.get("areaName", [{}])[0].get("value", location)

        if extensions == "base":
            return (
                f"【{city} 实时天气】\n"
                f"天气状况：{c.get('lang_zh', [{}])[0].get('value', c.get('weatherDesc', [{}])[0].get('value', '未知'))}\n"
                f"温度：{c.get('temp_C', '未知')}℃\n"
                f"体感温度：{c.get('FeelsLikeC', '未知')}℃\n"
                f"湿度：{c.get('humidity', '未知')}%\n"
                f"风速：{c.get('windspeedKmph', '未知')} km/h\n"
                f"能见度：{c.get('visibility', '未知')} km\n"
                f"更新时间：{c.get('observation_time', '未知')}"
            )
        else:
            # 未来几天预报
            forecast = data.get("weather", [])
            if not forecast:
                return f"未查询到 {location} 的天气预报数据"

            def _get_weather_desc(day_item):
                """从天气数据中提取天气描述（优先中文，其次英文）"""
                # 先看顶层 weatherDesc
                desc_list = day_item.get("weatherDesc") or []
                zh_list = day_item.get("lang_zh") or []
                if zh_list and isinstance(zh_list, list) and len(zh_list) > 0:
                    val = zh_list[0].get("value", "").strip()
                    if val and val.lower() != "unknown":
                        return val
                if desc_list and isinstance(desc_list, list) and len(desc_list) > 0:
                    val = desc_list[0].get("value", "").strip()
                    if val and val.lower() != "unknown":
                        return val
                return ""

            lines = [f"【{city} 天气预报】"]
            for i, day in enumerate(forecast[:3]):
                date = day.get("date", "未知日期")
                # 1) 先试 day 顶层 weatherDesc
                day_desc = _get_weather_desc(day)
                # 2) 如果为空，再从 hourly 取中午时段的描述
                if not day_desc:
                    hourly = day.get("hourly") or []
                    if hourly and isinstance(hourly, list) and len(hourly) > 0:
                        mid_idx = min(len(hourly) - 1, len(hourly) // 2)
                        day_desc = _get_weather_desc(hourly[mid_idx])
                if not day_desc:
                    day_desc = "未知"
                max_t = day.get("maxtempC", "未知")
                min_t = day.get("mintempC", "未知")
                lines.append(f"\n第 {i+1} 天 ({date})：")
                lines.append(f"  天气：{day_desc}")
                lines.append(f"  温度：{min_t}~{max_t}℃")
            return "\n".join(lines)

    except requests.exceptions.Timeout:
        return "错误：请求天气服务超时"
    except requests.exceptions.RequestException as e:
        return f"错误：天气服务请求失败 - {e}"
    except Exception as e:
        return f"错误：解析天气数据失败 - {e}"


@tool("search_knowledge_base")  # 用langchain的tool装饰器标记为Agent工具，名称为search_knowledge_base
def search_knowledge_base(query: str) -> str:
    """
    Agent工具函数：使用混合检索（稠密+稀疏向量）在知识库中搜索信息
    :param query: 用户的查询关键词
    :return: 格式化的检索结果字符串
    """
    # 全局变量：统计本轮工具调用次数
    global _KNOWLEDGE_TOOL_CALLS_THIS_TURN
    # 限制：本轮最多调用1次知识库工具
    if _KNOWLEDGE_TOOL_CALLS_THIS_TURN >= 1:
        return (
            "TOOL_CALL_LIMIT_REACHED: search_knowledge_base has already been called once in this turn. "
            "Use the existing retrieval result and provide the final answer directly."
        )
    # 调用次数+1
    _KNOWLEDGE_TOOL_CALLS_THIS_TURN += 1

    # 导入RAG流水线函数（实际检索逻辑在rag_pipeline.py中）
    from rag_pipeline import run_rag_graph

    # 执行RAG检索，获取结果
    rag_result = run_rag_graph(query)

    # 解析检索结果：文档列表
    docs = rag_result.get("docs", []) if isinstance(rag_result, dict) else []
    # 解析检索结果：追踪信息（用于调试/展示）
    rag_trace = rag_result.get("rag_trace", {}) if isinstance(rag_result, dict) else {}
    # 如果有追踪信息，保存到全局上下文
    if rag_trace:
        _set_last_rag_context({"rag_trace": rag_trace})

    # 如果没有找到相关文档
    if not docs:
        return "No relevant documents found in the knowledge base."

    # 格式化检索结果
    formatted = []
    for i, result in enumerate(docs, 1):  # 从1开始计数
        source = result.get("filename", "Unknown")  # 文档文件名
        page = result.get("page_number", "N/A")     # 文档页码
        text = result.get("text", "")               # 文档内容片段
        # 拼接单条结果
        formatted.append(f"[{i}] {source} (Page {page}):\n{text}")

    # 拼接所有结果并返回
    return "Retrieved Chunks:\n" + "\n\n---\n\n".join(formatted)


# 全局变量：Qwen模型实例（懒加载）
_QWEN_MODEL = None

def _get_qwen_model():
    """懒加载Qwen模型实例"""
    global _QWEN_MODEL
    if _QWEN_MODEL is None:
        # 从环境变量读取配置并初始化
        _QWEN_MODEL = init_chat_model(...)
    return _QWEN_MODEL

@tool("qwen_text_completion")
def qwen_text_completion(prompt: str) -> str:
    """
    Agent工具函数：调用Qwen文本模型进行文本生成
    适用于需要深度思考、创意写作、复杂推理等场景
    """
    qwen_model = _get_qwen_model()
    result = qwen_model.invoke(prompt)
    return result.content


# 在 tools.py 中添加完整的焊接检测工具
@tool("welding_detection")
def welding_detection(image_base64: str) -> str:
    """
    Agent工具函数：使用YOLO模型检测焊接质量，返回带检测框的图片
    :param image_base64: 图片的Base64编码字符串
    :return: JSON格式的检测结果（包含检测后图片）
    """
    import base64
    import cv2
    import numpy as np
    import json
    
    # 1. 解码Base64图片
    try:
        image_data = base64.b64decode(image_base64)
        np_arr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"图片解码失败: {str(e)}"})
    
    # 2. 调用YOLO模型检测
    try:
        # 加载YOLO模型（懒加载）
        yolo_model = _get_yolo_model()
        results = yolo_model(image)
        
        # ========== 新增：绘制检测框并返回图片 ==========
        # YOLOv8自动绘制检测框（带标签和置信度）
        annotated_image = results[0].plot()  # 获取带检测框的图片
        
        # 将绘制后的图片转换为Base64
        _, buffer = cv2.imencode('.jpg', annotated_image)
        result_image_base64 = base64.b64encode(buffer).decode('utf-8')
        # ========== 新增结束 ==========
        
        # 3. 解析检测结果
        issues = []
        for result in results.xyxy[0]:  # YOLOv8返回格式
            x1, y1, x2, y2, conf, cls = result
            class_name = yolo_model.names[int(cls)]
            issues.append({
                "type": class_name,          # 问题类型：虚焊、焊锡过多等
                "confidence": float(conf),   # 置信度
                "location": {               # 位置信息
                    "x1": float(x1),
                    "y1": float(y1),
                    "x2": float(x2),
                    "y2": float(y2)
                }
            })
        
        # 4. 生成改进建议
        suggestions = _generate_welding_suggestions(issues)
        
        # 5. 格式化结果（包含检测后图片）
        return json.dumps({
            "status": "success",
            "issues": issues,
            "suggestions": suggestions,
            "total_issues": len(issues),
            "result_image_base64": result_image_base64  # ✅ 返回检测后的图片
        })
        
    except Exception as e:
        return json.dumps({"status": "error", "message": f"检测失败: {str(e)}"})


def _generate_welding_suggestions(issues):
    """根据检测结果生成改进建议"""
    suggestions = []
    for issue in issues:
        issue_type = issue["type"]
        if issue_type == "cold_solder":
            suggestions.append(f"⚠️ 虚焊（位置: ({issue['location']['x1']:.1f}, {issue['location']['y1']:.1f})）：建议重新焊接，确保焊点牢固")
        elif issue_type == "excess_solder":
            suggestions.append(f"⚠️ 焊锡过多（位置: ({issue['location']['x1']:.1f}, {issue['location']['y1']:.1f})）：建议使用吸锡器清理")
        elif issue_type == "solder_ball":
            suggestions.append(f"⚠️ 焊锡球（位置: ({issue['location']['x1']:.1f}, {issue['location']['y1']:.1f})）：可能导致短路，建议清理")
        else:
            suggestions.append(f"⚠️ {issue_type}（位置: ({issue['location']['x1']:.1f}, {issue['location']['y1']:.1f})）：请检查焊点质量")
    return suggestions


# 新增：YOLO模型懒加载函数
def _get_yolo_model():
    """懒加载YOLOv8焊接检测模型"""
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        try:
            from ultralytics import YOLO
            # 加载预训练的焊接检测模型
            _YOLO_MODEL = YOLO("welding_detection_model.pt")  # 替换为你的模型路径
        except Exception as e:
            print(f"YOLO模型加载失败: {e}")
            _YOLO_MODEL = "error"
    return _YOLO_MODEL

# 全局变量：YOLO模型实例
_YOLO_MODEL = None