"""Editorial line explanations; building fails if any source line lacks an explanation."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
REVIEWED=json.loads((ROOT/'docs/guide/reviewed_source_hashes.json').read_text())
FILES={}
def add(path, purpose, text):
    digest=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    if REVIEWED.get(path)!=digest:
        raise ValueError(f'Source changed since line explanations were reviewed: {path}. Update the explanations and reviewed_source_hashes.json together.')
    notes={}
    for row in text.strip().splitlines():
        number, desc=row.split('|',1)
        notes[int(number)]=desc
    lines=(ROOT/path).read_text().splitlines()
    entries=[]
    for i,code in enumerate(lines,1):
        desc=notes.pop(i,None)
        if not code.strip():
            desc=desc or '空行。仅把相邻概念分开，Python/Bash 不会因这一行执行任何操作。'
        if not desc:
            raise ValueError(f'Missing explanation: {path}:{i}: {code}')
        entries.append({'line':i,'code':code,'explanation':desc})
    if notes: raise ValueError(f'Explanations without source lines: {path}: {notes}')
    FILES[path]={'purpose':purpose,'sha256':hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),'lines':entries}

add('analog_agents/__init__.py','包初始化文件。import analog_agents 或执行 -m analog_agents.run 时会经过它；这里只有说明，不运行实验。','''
1|三引号包说明：本包是使用本地 Qwen 进行模拟电路工作流实验的 Agent 代码。没有函数调用、网络请求或 GPU 操作；Python 把它保存为模块文档字符串。
''')
add('analog_agents/config.py','统一读取项目配置并限制项目文件路径。启动服务、API 客户端测试和正式实验都会用它。','''
1|导入 Python 标准库 json，后面将 settings.json 文本转换为 Python 字典；不是安装新库。
2|从标准库 pathlib 取出 Path 类，用它组合、解析和读取文件路径。
4|__file__ 是当前 config.py 的文件名；resolve 得到真实绝对路径；parents[0] 是 analog_agents 文件夹，parents[1] 是 /home/xu，因此 ROOT 是项目根目录。
6|定义 project_path 函数，输入 relative 是希望访问的项目相对路径，也能接收绝对路径；函数定义此刻不访问文件。
7|Path 的 / 运算连接 ROOT 和 relative，再 resolve 消除 .. 并解析符号链接。若输入是绝对路径，Path 会采用该绝对路径，所以下行仍必须检查边界。
8|判断解析后的真实路径是否不在 ROOT 内。not 表示取反，冒号后的缩进部分仅在越界时执行。
9|越界就抛 ValueError，中断本次操作；f 字符串将请求路径填进报错文字。这防止配置路径逃出项目，不是限制所有第三方系统调用的操作系统沙盒。
10|路径合法时 return 返回 Path 对象。这里只算路径，并没有打开或创建文件。
12|定义 load_config 函数，负责读取并检查集中配置。
13|先 project_path 定位 config/settings.json，再 read_text 读文本，最后 json.loads 解析成字典 cfg。文件缺失或 JSON 错误会抛异常。
14|对 cfg 中 model_dir 再做项目边界检查；没有检查该目录的所有权重是否已下载。
15|assert 要求 gpu 是非负整数。and 要求两个条件同时为真；失败抛 AssertionError。assert 在 Python -O 优化模式会被禁用，本项目启动命令没有使用 -O。
16|限制端口在 1024—65535 之间，避免使用低编号特权端口。此行不检查端口是否已经被别的程序占用。
17|限制 vLLM 显存预算比例在 0.1—0.6 之间。它不是限制 GPU 计算利用率。
18|限制上下文长度在 1024—32768 token 之间，这是项目允许范围，不是动态计算当前模型可承受的显存。
19|限制最多参数更新次数在 1—10 之间；主循环会额外加一次初始评估。
20|只允许 simulation_backend 为 mock，否则报出英文说明。目前改成 ngspice 不会自动接入真实仿真器。
21|把经过检查的字典 cfg 返回给调用者；后续代码通过 cfg[字段名] 使用设置。
''')
add('analog_agents/client.py','所有角色共用的请求实现。负责连接本地 vLLM、构造消息、解析并校验 JSON；本文件不直接调用 torch 或 GPU。','''
1|导入 json，用于把请求字典转成文本，以及把模型返回文本解析成字典。
2|从已安装 openai 包导入 OpenAI 客户端类；包名不表示一定访问云端，实际目标由 base_url 决定。
4|定义 LocalClient 类，封装本地模型通信。实例化后可以重复调用 ask。
5|构造函数 __init__ 在 LocalClient(cfg) 时执行；self 是新客户端对象，config 是传进来的配置字典。
6|保存配置引用为 self.config，后面的请求会从这里取模型名和生成设置。
7|创建 SDK 客户端并保存在 self.api。f 字符串把 port 替换进本机 URL；末尾 /v1 是 API 基础路径，此时通常还没有发送推理请求。
8|继续上行构造：local-only 是占位 key，timeout 使用配置值；max_retries=1 允许某些请求失败后再试一次。右括号结束 OpenAI(...) 调用。
10|定义 ask 方法，三个输入分别为角色提示词 prompt、任务资料 payload、输出格式规则 schema。
11|调用 SDK 的聊天生成方法，真正向服务发请求并等待结果，返回对象命名为 response；后面缩进续行都是本次调用的参数。
12|将模型 API 别名传给 model，不是远程仓库路径；必须与服务 --served-model-name 一致。
13|建立消息列表第一项 system：角色提示词加一句要求 JSON 的说明，再加 schema 的 JSON 文本。反斜线 n 表示换行；这里把规则也写进模型可见文字。
14|第二项 user 保存本次上下文 payload 的 JSON 文本；ensure_ascii=False 保留中文，而不是写成 Unicode 转义。方括号结束两条消息列表。
15|temperature 设置采样随机程度，max_tokens 限制这次最多生成多少 token；两项从集中配置读取。
16|extra_body 是扩展字段：enable_thinking=False 控制 Qwen3 模板，guided_json 将 Schema 传给 vLLM 的结构化生成机制。右括号结束请求，程序等待它返回。
17|取 choices 列表第 0 个候选答案；默认请求只需要一个候选，不是在四个 Agent 中选第一个。
18|检查生成结束原因是不是 stop。此处字符串 stop 与优化 JSON 中的布尔 stop 不是同一个变量。
19|如果输出因长度等原因中断，抛 ValueError 并带出原因，避免把截断 JSON 当成完成结果。
20|把模型消息正文从字符串解析为 Python 字典。若正文包含非 JSON 文本或损坏格式，这一步会抛 JSONDecodeError。
21|导入 jsonschema 库的 validate 函数，准备在客户端再次检查响应；该导入位于函数内部，执行到这里才发生。
22|检查 result 是否满足这个 Agent 的 Schema：字段名、类型、范围等。失败会抛 ValidationError，不会自动修复或再次问模型。
23|校验成功后返回 result 给 Agent.run，再返回给主流程。没有在这里保存响应文件；保存由 run.py 或测试脚本负责。
''')
add('analog_agents/agents.py','定义角色允许返回的数据结构，以及所有角色共享的 Agent 类。SCHEMAS 的键名必须和 prompts 文件名、run.py 中的角色名称对应。','''
1|从同一包的 config.py 导入路径检查函数。开头 . 表示相对当前 analog_agents 包，不是磁盘当前工作目录。
3|定义 obj 辅助函数，接收一个“字段名 -> 字段规则”的字典，组装对象类型的 JSON Schema。
4|返回 Schema：type=object 要求字典；properties 描述各字段；required=list(properties) 将所有字段名设为必填；additionalProperties=False 拒绝未声明字段。
6|TEXT 是字符串字段的通用规则，供 rationale 等字段复用；不是提示词正文。
7|调用 obj，开始建立六个电路参数的共同规则 PARAMETERS；后面的字典是传给 obj 的参数。
8|input_w_um 为输入对晶体管宽度，单位微米；必须是数值，范围 1—200。number 可含小数，不限整数。
9|input_l_um 为沟道长度，范围 0.18—5 微米；当前概念模板把它用于所有 MOS，不是只有输入对。
10|load_w_um 为 PMOS 镜像负载宽度，范围 1—400 微米。
11|stage2_w_um 为第二级 PMOS 宽度，范围 1—400 微米。
12|bias_ua 为演示偏置电流，范围 1—300 微安；网表尾电流使用它，第二级理想电流源使用它的两倍。
13|compensation_pf 为补偿电容，范围 0.1—20 皮法；大于零也避免 Mock 带宽计算除以零。
14|} 结束六字段字典，) 结束 obj 调用；其返回值赋给 PARAMETERS。
15|建立 SCHEMAS 字典，以角色名字索引各自输出规则。
16|architecture 必须返回 topology、rationale、assumptions。topology 用 enum 只允许 two_stage_cmos_opamp；assumptions 是字符串数组。当前不接受任意 ADC 架构名。
17|sizing 必须返回 parameters 和 rationale；parameters 复用上面的六参数规则。
18|simulation 必须返回 analyses 与 rationale。analyses 至少一个元素，每项仅允许 op/ac/tran；这里没有 uniqueItems，所以规则本身不禁止重复分析名称。
19|optimization 必须返回完整 parameters、rationale 和布尔 stop。即使只改一个参数，也要把另外五项返回。
20|结束 SCHEMAS 字典定义；此前都是规则数据，没有向模型请求设计。
22|定义统一 Agent 类，不为四个角色各复制一套网络代码。
23|构造 Agent 时接收角色名字 name 和已建立的客户端 client。
24|同时保存名字和客户端到 self.name、self.client，后面据此找提示词和 Schema。
25|把名字填进 prompts/{name}.md，从项目目录读取整段文字，存到 self.prompt。比如 sizing 对应 prompts/sizing.md；这里只读一次。
27|定义 run 方法，参数 context 是该次要让角色看到的任务资料字典。
28|把角色文字、上下文和对应 Schema 传给 LocalClient.ask，并把返回字典原样交回。Agent 类自身不写结果文件、不运行仿真器。
''')
add('analog_agents/run.py','正式实验的 Python 入口，由 scripts/run_demo.sh 用 -m analog_agents.run 启动。负责顺序、数据传递、迭代、文件保存和错误报告。','''
1|导入 json，以便将配置、角色回答和历史记录写成 JSON 文本。
2|导入 datetime 类，用于取得当前时间并制作实验目录名。
3|导入 ZoneInfo，让时间戳明确采用 Asia/Tokyo 时区，而不是任意机器的默认时区。
4|导入配置读取与项目路径检查，所有主要输入/输出路径从这层定位。
5|导入 LocalClient 类，后面为角色建立 API 客户端。
6|导入统一 Agent 类，后面用不同角色名实例化四次。
7|导入 MockSimulation 工具类；这明确决定当前执行的是 Mock，不是真实 SPICE。
9|定义 main 主函数。文件底部会在直接执行模块时调用它。
10|实际调用 load_config，读取并检查 config/settings.json，结果保存在 cfg。
11|获取日本时区当前时间并格式化成 年月日-时分秒-微秒 的字符串，减少多次实验目录重名。
12|拼接 outputs/时间戳 并做项目边界检查，得到输出目录 Path 对象 out。
13|真正创建实验目录；parents=True 允许同时创建缺失的上级目录。没有 exist_ok=True，若精确同名目录已存在会报错。
14|在 main 内定义辅助函数 save，两个输入是文件名和待保存的数据；它能使用外层 out。
15|把 value 转成带两空格缩进、保留中文的 JSON 文本，并写到 out/name。write_text 覆盖已有同名文件，不是追加。
16|保存本次配置快照为实验目录的 config.json，方便以后复现设置。
17|字典推导式：依次为四个名字创建 LocalClient(cfg) 和 Agent，再形成“名字 -> Agent 对象”的字典。客户端有四个，后端模型服务仍是同一个。
18|创建初始上下文字典，只含设计 specification。以后还会把架构、尺寸回答加进去。
19|创建空列表 history，用来记录各轮已经计算的结果。
20|开始异常保护区。这里之后、except 之前的错误会尝试写 failure.json；前面读取配置或读取提示词出错不在这个保护区。
21|按固定顺序依次遍历 architecture 和 sizing，name 在两次循环中取不同值。
22|调用对应 Agent，把当前 context 发给模型；返回字典存入 context[name]。第二次 sizing 因此可以看到第一次的架构结果。
23|保存对应角色输出为 architecture.json 或 sizing.json，不改变模型回答里的字段。
24|终端打印该角色已完成；flush=True 立即刷新输出，避免长任务中提示被缓冲。
25|从尺寸回答中取出 parameters 字典，作为当前迭代参数 params；初始 rationale 仍在 context 中保留。
26|注释说明循环语义：初始评估一次，之后最多 max_iterations 次参数更新。注释本身不执行。
27|range(2+1) 产生 0、1、2；每个 step 对应一次评估。Python range 不包含右端点。
28|构造本轮子目录名 iteration-0、iteration-1 等。
29|实际创建本轮目录，供网表文件保存。
30|调用 simulation Agent，传入 context 展开的字段和当前 parameters。后面的 parameters 字段是迭代当前值，不是初始 sizing 记录。
31|创建 MockSimulation 工具并立即运行；四个输入是当前尺寸、目标指标、模型选出的分析列表和本轮输出目录；返回 Mock 指标字典 result。
32|把迭代编号、当前参数、分析计划和计算结果组装成 record 字典，形成可追踪的单轮记录。
33|把 record 对象放入 history。这里保留对象引用，后面给 record 添加优化建议时，同一 history 元素也会变化。
34|把截至本轮的完整 history 写入 history.json，在问优化角色之前先保留已完成评估。
35|在终端明确打印 MOCK 和当前指标，避免把它误认为实测电路结果。
36|判断当前轮是不是允许的最后一轮评估。达到上限时不再问优化 Agent。
37|从最近的 for step 循环跳出；后面的保存 summary 仍会继续执行。
38|请求 optimization Agent；把指标/初始设计 context 与当前 record 展开成一个输入字典。默认没有传整个 history。
39|将模型优化建议加入当前 record，包含完整下一轮参数、理由和 stop；history 中该轮记录随之更新。
40|再次保存 history.json，这次把刚获得的优化建议也写进去。
41|and 要求模型建议停止和 Python 的合成目标判断同时为真，才走下面 break；仅模型声称完成不够。
42|两个条件都满足时提前离开迭代循环。此时本次 advice 的新参数没有再被应用或评估。
43|否则把优化输出参数指定为下一轮 params，然后循环回到本轮 for 开头；没有原地改旧字典，也没有比较建议是否变好。
44|循环结束开始写 summary.json：completed 表示流程走完，llm_backend 标注本地 Qwen，simulation_backend 标注 mock。
45|继续 summary 字典：真实电路未验证，评估次数是 history 长度，final 取最后一条记录；这里没有搜索“最佳”记录。
46|捕获 try 中发生的大多数普通异常，命名为 exc；不会捕获所有系统级终止情形，例如 KeyboardInterrupt 不属于 Exception。
47|在实验目录写 failure.json，记录失败状态和错误文字。若文件系统自身无法写入，这次记录也可能失败。
48|重新抛出原异常，使终端能看到调用栈并让进程失败退出，而不是打印失败后继续伪装成功。
49|正常完成后打印结果目录，便于用户找到此次实验的产物。
51|当模块通过 -m 直接执行时 __name__ 为 __main__；被其他文件 import 时通常不是，因此不会自动跑实验。
52|调用上面定义的 main()，这是控制权进入正式工作流的具体位置。
''')
add('analog_agents/simulation.py','工具接口与合成仿真实现。模型只提出分析计划，本文件用 CPU 生成概念网表并计算人为公式；不存在真实仿真器子进程。','''
1|模块文档字符串明确说明合成后端和“不执行模型生成代码”的边界，不是程序指令。
2|导入标准数学库，主要使用以 10 为底的对数 log10。
3|导入 Protocol，用来声明未来仿真工具应有的方法形状；它不是一个实际仿真器。
4|导入 JSON Schema 校验函数，保证传进来的尺寸有完整字段、正确类型且在允许范围内。
5|从 agents.py 复用 PARAMETERS，避免 Agent 和工具各自定义不同的参数边界。
7|把 Mock 公式保存为文字，随结果传给优化 Agent 参考。这一字符串本身不参与计算；真正计算在下面 metrics 中，改公式时要同时维护两处。
9|定义 Simulator 协议类型，表示兼容的工具应提供 run 方法；当前 MockSimulation 没有显式继承它，也没有强制运行时注册。
10|声明 run 需要哪些参数以及返回 dict；... 是省略号占位符，表示这里没有真实算法，不会自动调用仿真器。
12|定义 netlist 函数，输入 p 是尺寸字典、spec 是目标/供电信息、analyses 是所选分析名称；输出电路文本。
13|先检查 p 是否满足 PARAMETERS，拒绝缺字段、字符串冒充数字或不合理范围。
14|注释强调固定连接模板、只插入数字、LEVEL=1 模型不是工艺 PDK，提醒不可把它当作可靠器件模型。
15|按 PARAMETERS 中字段插入顺序读取六个值，解包成 w/l/load/stage/bias/cc。改字段顺序或数量会影响这里，因此正文给出了按字段名逐项读取的替换方法。
16|把分析名字映射成 SPICE 文本：op 是工作点，ac 是从 1 Hz 到 1 GHz 每十倍频程 50 点，tran 是示意 1 ns 步长到 10 us。这里仅生成字符串。
17|开始返回多行 f 字符串，花括号里的 Python 表达式会换成实际值；首行 * 是 SPICE 注释，明确未执行、无 PDK。
18|仍在多行字符串内，是网表注释，说明 NMOS 输入对、PMOS 镜像和 PMOS 第二级；不是 Python 乘法。
19|网表电压源 VDD 从 vdd 节点到地 0，电压取 spec 的 vdd_v。
20|正输入电压源的直流共模是供电一半，AC 幅度 0.5；只是概念网表的激励定义。
21|负输入电压源同样共模，AC 幅度 0.5 且相位 180 度，构成一对反相小信号输入。
22|从 tail 到地的理想尾电流源，数值为 bias 微安。没有使用真实晶体管偏置网络。
23|M1 是输入对第一管，节点顺序漏/栅/源/体为 n1、inp、tail、0，模型 NM；W 和 L 插入微米数值。
24|M2 是输入对第二管，漏极 n2、栅极 inn，其余与第一管类似。
25|M3 是二极管连接 PMOS，漏/栅都为 n1，源/体为 vdd；load 是其宽度。
26|M4 是 PMOS 镜像另一支路，漏在 n2、栅在 n1，复制镜像偏置关系；这里没有计算镜像精度。
27|M5 是第二级 PMOS 共源管，漏为 out、栅为 n2、源/体为 vdd，宽度取 stage。
28|第二级输出到地的理想电流源，设置为两倍 bias 微安；这是演示假设，不是优化算法推导出的完整偏置设计。
29|补偿电容 CC 接在第一级输出 n2 与最终输出 out 之间，单位皮法。
30|负载电容 CL 从输出到地，使用 specification.load_pf。
31|定义名为 NM 的简化 NMOS LEVEL=1 模型；阈值 0.45、KP=120u、LAMBDA=0.04 是示例数值，不是代工厂参数。
32|定义 PM 的简化 PMOS 模型；负阈值和不同 KP 体现符号/类型差异，依旧不是工艺验证模型。
33|结束多行模板；依 analyses 逐项取 commands，以换行连接并附加 .end。return 整段字符串。没有调用 ngspice，也没有执行 .op/.ac/.tran。
35|定义 MockSimulation 类，提供当前实际被 run.py 使用的工具。
36|定义工具 run 方法，接收尺寸、规格、分析列表、输出目录。
37|在工具入口再次校验尺寸；即使将来有人绕开 Agent 直接调用工具，也会有这道检查。
38|调用上面的 netlist 生成文字，并写成当前轮目录的 conceptual_not_executed.cir。工具随后不读取这个文件来计算指标。
39|为 parameters 起一个较短别名 p；没有复制数据，也没有修改参数。
40|开始 metrics 字典，gain_db 使用 45+12*log10(W/L) 的合成公式，round(...,3) 保留三位小数。这里只是教学映射，不是晶体管小信号推导。
41|合成带宽为 0.8*偏置电流/补偿电容，保存为 ugb_mhz，保留三位小数。
42|合成相位裕度为 45+12*补偿电容-0.2*负载电容，并用 min 限制最大 89 度；保留三位小数。
43|合成功耗为供电*3*偏置/1000，单位毫瓦，保留四位小数；闭合 metrics 字典。
44|对增益、带宽和相位裕度三个指标，逐个比较 metrics[k] 是否大于等于 spec[k+"_min"]，产生真/假的 checks 字典。
45|功耗是越小越好，因此单独与 power_mw_max 用 <= 比较，而不是沿用前三项的 >=。
46|开始返回结果字典，明确 backend=mock、synthetic=True、real_spice_executed=False，阻止来源被误解。
47|附带中文警示说明这些数字只适合软件流程测试，不能用于真实电路或流片判断。
48|附上指标、每项检查及 all(checks.values())；all 只有在每个布尔值都为真时才返回真。
49|把上面保存的公式文字也交回，让优化角色知道它正在优化什么合成规则；结束返回字典。
''')
add('scripts/env.sh','每个日常 shell 入口都会 source 本文件，统一环境变量和缓存路径。export 让随后启动的 Python 子进程也继承这些设置。','''
1|shebang 声明用 Bash 解释脚本；被 source 时由当前 shell 解释，此行作为注释不另起进程。
2|BASH_SOURCE[0] 取本脚本路径，dirname 取 scripts 目录，/.. 上到根目录；子命令在自己的上下文中 cd，pwd -P 给出真实目录。export PROJECT_ROOT 把结果传给后续程序，不改变用户 HOME。
3|将标准临时目录变量 TMPDIR 指向项目 .runtime/tmp，Python tempfile 等组件通常据此选择临时目录。
4|同时设置 TMP 和 TEMP，兼容使用其他临时目录变量名的软件；值都与 TMPDIR 相同。
5|把遵守 XDG 约定的软件缓存放在项目 .runtime/cache。
6|把遵守 XDG 约定的软件配置放在项目 .runtime/config。
7|把遵守 XDG 约定的持久数据放在项目 .runtime/data。
8|把遵守 XDG 约定的运行状态放在项目 .runtime/state。
9|为 uv 指定项目内缓存目录，供下载安装时使用。
10|指定 uv 安装独立 Python 解释器的位置 .runtime/python。
11|指定 uv Python 可执行文件链接的存放位置 .runtime/bin；不要求添加到全局 shell 配置。
12|指定 pip 缓存路径；某些安装命令还使用 --no-cache-dir 主动关闭该缓存。
13|指定 Hugging Face 的缓存/本地配置根目录，避免使用默认的其他位置；模型权重另有显式 local_dir。
14|禁用自动附带已有 token 和 Hugging Face 遥测；下载公开模型不需要你提供云端 API 密钥。
15|指定 PyTorch 自身的缓存目录。
16|指定 PyTorch 扩展编译产物的目录，即使某项依赖需要生成扩展也留在项目内。
17|指定 Triton 内核编译缓存目录，用于 GPU 运算相关依赖。
18|指定 NVIDIA CUDA 编译缓存路径。
19|指定 vLLM 缓存根目录。
20|指定 vLLM 配置根目录，和模型权重目录不同。
21|指定 Numba 的编译缓存目录。
22|指定 Matplotlib 配置/缓存目录；当前日常 Agent 流程未绘图，但预先约束可能使用它的库。
23|PYTHONNOUSERSITE 避免从用户默认 site-packages 混入包；PYTHONDONTWRITEBYTECODE 阻止生成 .pyc 字节码缓存，但不禁止所有文件写入。
24|关闭 vLLM 使用统计，并给识别这些变量的组件声明不追踪；并非操作系统级的网络阻断器。
25|限制 OpenMP CPU 线程为 4，并禁用分词器并行，减少共享 CPU 资源争用；不代表 vLLM 所有内部线程都精确只有 4 个。
26|禁用 NCCL 的共享内存传输路径，设置 vLLM 主机地址为本机回环。GPU 运算仍可运行；不是禁用 CUDA。
27|让 Python 的模块搜索路径包括项目根目录，这样直接运行 scripts/ 下的文件也能 import analog_agents。
28|创建最基本的临时、缓存、配置、数据、状态目录；mkdir -p 在目录已存在时不报错，也不删除旧内容。许多更深的缓存子目录由对应库按需创建。
''')
add('scripts/activate.sh','用户用 source 运行，修改当前终端的环境。它本身不启动模型、不运行实验。','''
1|声明 Bash 脚本；当前终端 source 时作为注释处理。
2|从本脚本所在目录找 env.sh 并在当前 shell 中执行，让 PROJECT_ROOT 与缓存变量生效；子命令里的 cd 不把终端留在 scripts 目录。
3|在当前 shell 执行项目虚拟环境的自动激活脚本，将 python 等命令优先指向 .venv。完整自动脚本也在后面附录中解释。
''')
for path, last in [
 ('scripts/start.sh','用 exec 将当前 shell 进程替换成项目 Python，执行 scripts/service.py，传入 start；之后由服务管理代码创建后台 vLLM。'),
 ('scripts/stop.sh','用 exec 执行项目 Python 的 scripts/service.py，并传入 stop；只停止状态文件记录的项目进程组。'),
 ('scripts/test_qwen.sh','用 exec 执行项目 Python 的 scripts/test_qwen.py，运行一次真实本地 API 测试。'),
 ('scripts/run_demo.sh','用 exec 执行项目 Python，-m analog_agents.run 表示作为包模块启动主流程。"$@" 原样转发额外命令行参数；当前 run.py 没有参数解析，因此附加 --foo 等选项不会自动改变配置。')]:
 add(path,'日常 Bash 入口。使用绝对的虚拟环境 Python 路径，即使没有手动激活也不会意外选中系统 Python；仍需先启动模型才能调用 API。',f'''
1|shebang 声明这是 Bash 文件；日常用 bash 文件名 显式解释。
2|set -e 让通常的命令失败中断脚本，-u 拒绝未定义变量，pipefail 使管道中间失败也可传播；Bash 某些条件语境有例外，不能看作完整异常处理。
3|根据脚本文件位置 source 同目录 env.sh，统一 PROJECT_ROOT 和缓存/临时环境。
4|把当前子进程工作目录切到 PROJECT_ROOT，使后续 scripts/... 相对路径有确定含义。
5|{last}
''')
add('scripts/service.py','模型服务的启动和停止管理器。它会读配置、GPU 状态和服务状态，启动第三方 vLLM 入口；本文件自己不实现神经网络。','''
1|模块说明：仅单 GPU、仅本机接口，只停止自己创建的进程组。三引号说明不执行管理操作。
2|导入 Linux 文件锁接口 fcntl，防止两个管理命令同时操作状态。
3|导入 json，用于保存和读取服务 PID/启动命令等数据。
4|导入 os，用于复制环境变量和向进程组发信号。
5|导入 signal，使用有名称的 SIGTERM 常量，要求进程正常终止。
6|导入 socket，用于启动前临时检查监听端口能否绑定。
7|导入 subprocess，用于运行 nvidia-smi 和创建 vLLM 后台子进程。
8|导入 sys，读取当前 Python 可执行路径 sys.executable 和用户命令参数 sys.argv。
9|导入 time，为启动/停止的轮询之间加入短暂等待。
10|导入标准库 HTTP 请求工具，用来访问本地 /health 健康检查接口。
11|从项目配置模块导入配置读取、路径检查和根目录常量。
13|计算服务状态文件路径 logs/service.json，保存为 STATE。此刻没有读取或创建该文件。
15|定义 birth(pid)，查询一个 Linux 进程的启动时刻标记，以识别 PID 是否被重用。
16|尝试读取进程信息；进程可能已经退出，所以必须处理文件不存在。
17|读取 /proc/PID/stat，先跳过括号包围的进程名，再按空格拆分，从后半部分第 20 项取原 stat 的 starttime 字段。这个值与 PID 组合用来区分不同生命周期的进程。
18|如果 /proc 文件不存在，说明查询时进程可能已经消失，进入这一分支。
19|返回 None 表示未取到出生标记，不是创建新进程。
21|定义 owned(state)，判断状态文件记录的进程与当前同 PID 的进程是否仍是同一个。
22|比较当前查询的 birth 与保存值；相同则返回 True。该方法依赖项目状态文件完整可信，不是通用操作系统所有权认证。
24|定义 stop 操作，下面正文等 service.py stop 分派到它时才执行。
25|先判断服务状态文件是否不存在。
26|无状态文件则打印“没有受管理的服务”，不会全局搜索并杀 Python。
27|提前返回，结束 stop。
28|有状态文件则读取 JSON，得到 pid、birth 等信息。
29|仅当进程出生标记吻合时，才执行下一步发信号操作。
30|向 PID 对应的进程组发送 SIGTERM。启动时 start_new_session=True 使该组属于本项目启动的服务；并不是按进程名匹配全部用户进程。
31|最多检查 60 次，_ 表示不使用这个循环序号。
32|查询当前 PID 是否已经不再对应记录进程。
33|进程已不在则退出等待循环，继续清理状态文件。
34|注释意图是把僵尸进程视为已退出。严格说 zombie 是已结束但尚待父进程回收的状态，注释中 reaped-by-parent 的措辞不严谨；此处不再继续等它。
35|读取进程状态文本，去掉进程名部分，为检查 Z 状态准备。
36|若后半部分以 Z 开头，说明进程是 zombie，已不在执行模型计算。
37|离开等待循环。GPU 释放和 nvidia-smi 更新仍可能有短暂延迟，需要另行查看。
38|若进程仍活动，等 0.5 秒再检查。
39|这是 Python for...else：只有循环用完 60 次而没有 break 时才执行，不是上面某个 if 的 else。
40|停止超时则抛错，让人查看日志，不会直接升级为强制 SIGKILL。
41|删除本项目服务状态文件；不删除模型、日志或实验输出。若记录 PID 不再属于原进程，也只清理这份旧状态。
42|打印受管理服务已停止。并非系统全部 GPU 都一定空闲的证明。
44|定义 start 操作，用于启动模型服务。
45|从 config/settings.json 读取集中配置，接下来使用 c 这个较短变量名。
46|如果状态文件存在并且仍对应同一进程，认为服务已启动。
47|抛出已有服务错误，避免同项目重复分配模型显存。
48|创建临时 socket，with 结束后自动关闭。
49|尝试绑定本机指定端口；端口已用时会抛 OSError。socket 很快关闭，所以这不是直到真正启动之间的原子端口预约。
50|运行 nvidia-smi 命令并选择配置中的卡号；使用列表传命令参数，不通过 shell 执行任意拼接代码。
51|继续指定查询 UUID、显存已用、总量和利用率，要求无表头无单位 CSV；text=True 得到字符串，strip 去掉首尾空白。
52|按逗号拆分返回值并逐项去空白，分别赋给 uuid/used/total/util。当前 total 被读取但没有用于额外显存充足性判断。
53|将已用显存和利用率转成整数，超过 1024 MiB 或 5% 就认为忙碌。
54|忙碌则抛错并报告观测值；不尝试终止其他作业，也不自动选择另一张卡。
55|把模型目录配置解析成经过边界检查的项目绝对 Path。
56|查看模型目录里的 config.json 是否存在，这只是最小存在性检查。
57|缺少配置就报错，提醒先下载模型；不在启动过程偷偷联网下载。
58|复制当前环境变量字典，后面只修改子进程使用的 env，不修改系统环境配置。
59|注释说明 vLLM 0.8.5 的 NVML 映射需要数字 CUDA_VISIBLE_DEVICES；先前使用 UUID 曾失败，因此这里使用编号。
60|对子进程限制可见 GPU 为配置的一张卡，采用 PCI_BUS_ID 排序；VLLM_USE_V1=0 指定该版本的 V0 引擎路径。
61|设置 Hugging Face/Transformers 离线，避免服务启动时访问远程；设置工作进程启动方法 spawn。右括号结束 env.update。
62|建立要运行的命令列表；sys.executable 是当前 .venv Python，-m 后面给第三方 vLLM 模块入口，--model 指向本地权重目录。
63|设置 API 对外模型别名、监听地址仅 127.0.0.1，以及端口。
64|权重/计算类型采用 bfloat16；最大输入加输出上下文使用配置值。BF16 是 16 位浮点表示，不是模型名称。
65|设置显存预算比例和张量并行大小 1，只用单卡而不是分到多卡。
66|同时处理的最大序列数为 2；enforce-eager 使用直接执行模式而非 CUDA 图捕获；关闭请求内容日志，关闭前端多进程。服务仍会输出运行和访问日志。
67|结构化生成后端设置 xgrammar；该 vLLM 版本对某些复杂 Schema 可能内部回退，最终客户端仍会 jsonschema 校验。
68|以追加模式打开 logs/qwen.log，保留旧启动记录，模型的输出写到这里。
69|真正创建后台 vLLM 进程：传递 env、工作目录 ROOT，把标准错误也并入同一日志；start_new_session 建立新会话，使启动管理器退出后服务继续运行。
70|记录 PID、出生标记、GPU UUID、端口和完整启动参数到状态文件；indent=2 便于人工阅读。
71|立即打印正在启动及 PID，提示用户查看日志；这还不是 Ready。
72|最多检查健康状态 300 次；每次还有请求超时与 sleep，因此不是严格 600 秒的硬上限。
73|poll 查询后台进程是否已退出。返回 None 表示还在运行，非 None 是退出码。
74|若服务已退出，移除失效状态文件；missing_ok=True 表示文件已不存在也不报错。
75|抛出服务启动失败，并提示查看 qwen.log，保留具体退出码。
76|尝试访问健康端点，加载期间连不上是可以暂时接受的情况。
77|发 GET 请求到本机 /health，单次连接/读取设置 2 秒超时；with 自动关闭响应对象。
78|HTTP 状态码 200 表示服务健康检查通过。
79|打印 Ready 和 API 基础地址，告诉使用者可以开始发送请求。
80|结束 start 函数，随后启动管理脚本结束；后台 vLLM 不因此停止。
81|捕获临时网络/操作系统错误和超时，常见于服务仍在加载模型。
82|pass 表示本次忽略该临时失败，不做其他动作，继续后续等待。
83|每轮等 2 秒，避免用紧密死循环不断请求服务。
84|检查次数耗尽仍未成功时，调用本文件 stop，尝试清理自己启动的服务。
85|清理后抛出启动超时错误，不能把这次启动标为成功。
87|只有脚本作为主程序执行时，才进行命令分派；import 本文件不会自动启动 GPU。
88|打开项目的 service.lock 文件作为互斥锁载体；with 结束时关闭文件并释放锁。
89|申请排他且非阻塞文件锁：若另一个管理操作持有锁，立即报错而不是一直等待。该锁不等于系统 GPU 排队机制。
90|构建 start/stop 对应函数字典，按 sys.argv[1] 选出函数并调用；argv[0] 是脚本名。未提供参数或拼错参数会报错，没有完整命令行帮助解析器。
''')
add('config/settings.json','用户集中配置。文件是 JSON 数据而非 Python。run.py 和 service.py 分别在各自启动时读取，因此更改服务相关字段需要重启后台。','''
1|左花括号开始最外层 JSON 对象；字段名要双引号，文件中不能添加 # 注释。
2|远程模型仓库名称。下载脚本使用它，运行中的服务主要使用本地 model_dir，不因改名字自动换权重。
3|固定的 Hugging Face 提交号，锁定下载快照。它不是 Python/vLLM 版本号，也不是本地文件路径。
4|模型权重保存在项目内的相对目录；启动服务将它转成 /home/xu/models/Qwen3-8B。
5|API 提供给客户端的模型别名。service.py 与 client.py 都用这个字段保持一致。
6|选择 nvidia-smi 中编号 0 的 GPU；这是一个整数，不是四张卡同时使用的数量。
7|本地服务端口号。服务和客户端都由此决定地址，更改后要重启旧服务。
8|最大上下文 token 长度 8192，包括输入和生成输出，并非字符数量。
9|vLLM 显存预算比例 0.5；实际显存有开销，且这不是 GPU 运算负载上限。
10|单次回答最多生成 1200 token，过小可能让 JSON 被截断；不是整个实验的 token 总预算。
11|采样温度 0.2，用于调节随机性，不是显卡温度。
12|SDK 网络超时设置 180 秒；多次请求与重试使整个 workflow 可能远超过这个时长。
13|最多允许两次参数更新，主循环因包含初始评估最多计算三轮。
14|仿真后端名为 mock。当前 Python 代码只接受它，改为其他文字不会自动获得新工具。
15|设计规格：circuit 是任务标签；vdd_v=1.8 伏，load_pf=5 皮法；增益至少 65 dB、单位增益带宽至少 10 MHz、相位裕度至少 60 度、功耗最多 1 mW。当前结果是合成指标。
16|右花括号结束 JSON 对象。最后字段后不应留下多余逗号。
''')
for name,desc in {
'architecture':'整行作为 system 提示词的一部分送给模型：要求两级运放、NMOS 输入对、PMOS 镜像和 PMOS 第二级、Miller 补偿；承认偏置源理想化和没有 PDK；用简洁中文说明假设。该行不创建电路，也不改变 Python 固定拓扑。',
'sizing':'整行说明尺寸角色要输出几何尺寸、偏置、电容，单位由字段名决定；共同沟道长度用于所有器件；必须说初值未验证，不能声称已保证指标；建议从 20/1/40/80/40/2 附近起步，后面由 Mock 与优化迭代。它只是模型指令，不是参数的硬编码赋值。',
'simulation':'整行要求从 op/ac/tran 中选分析并用中文说明；明确 Python 使用固定模板和 MockSimulation，不能声称真正执行 SPICE，不得输出 shell 命令。真正允许字段还受 agents.py 的 Schema 限制。',
'optimization':'整行要求读取 Mock 指标和目标，利用给出的合成公式给出受限参数更新、中文理由和停止建议；要求完整返回参数；不把合成优化说成真实电路设计。Python 最终仍会检查数值范围与停止条件。'
}.items():
 add(f'prompts/{name}.md','纯文本角色提示词，由 Agent.__init__ 读取。本文件只有一条物理长行，在 PDF 中会折行显示。','1|'+desc)
add('scripts/download_model.py','安装或主动更新模型时执行。日常启动模型与运行实验不会自动调用它。需要网络，权重与下载记录都位于项目目录。','''
1|导入 json，用于保存模型下载记录。
2|从 Hugging Face Hub 包导入 snapshot_download，它能按仓库快照下载匹配的文件。
3|导入集中配置读取和项目路径边界检查。
5|读取 settings.json，获得模型仓库、固定修订和本地目录；此脚本没有 main 保护，import 它也会执行下载逻辑，因此不要随意导入。
6|调用 snapshot_download，按 model_repo 和 model_revision 选择远程仓库的固定快照。
7|local_dir 显式指定项目内模型目录；max_workers=2 限制并行下载工作线程，不是使用两张 GPU。
8|仅下载列出的文件模式，包含配置、safetensors 权重、分词文本/模板和许可证说明；* 是文件名通配符。结束下载调用，函数返回本地路径。
9|只有上面下载正常返回才写 complete 记录到 logs/model_download.json，包含路径、仓库、修订。下载抛错时不会执行这一行。
10|打印模型文件所在路径，供用户确认；这不代表模型已加载到 GPU。
''')
add('scripts/install.sh','可重复安装的辅助脚本，不是日常运行入口。它优先同步 requirements.lock，最后下载模型；会联网但只针对项目环境。','''
1|声明 Bash 脚本。
2|启用常见错误时退出、未定义变量报错、管道失败传播，避免安装一半后忽略明显错误继续运行。
3|先 source env.sh，确保下载、缓存、临时目录都指向项目内。
4|切换到项目根目录，使相对环境和 requirements 路径稳定。
5|检测项目 uv 文件是否不是可执行文件，只有缺失时才做下一步引导安装。
6|用已有 python3 的 pip 把 uv 0.8.22 安装到 .runtime/tools。--target 限制安装目的地，--no-cache-dir 关闭 pip 下载缓存，--isolated 忽略用户 pip 配置与环境设置；临时目录仍由程序的环境决定。
7|fi 结束 uv 是否需要安装的条件分支。
8|用项目 uv 确保 Python 3.11.13 已安装；其目录由 UV_PYTHON_INSTALL_DIR 指定。
9|检查 .venv 目录是否不存在；已有环境时不会重新创建。
10|建立使用指定 Python 的 .venv，并用 --seed 提供 pip 等基础包；不是修改系统 Python。
11|结束虚拟环境创建条件。
12|检查项目是否有完整 requirements.lock 文件。
13|有锁文件就用 uv pip sync 使项目环境与锁定列表同步；可能移除未列出的包，因此不能把它理解为仅添加缺失依赖。
14|如果没有锁文件，进入备用安装方式。
15|按 requirements.txt 安装主要依赖，再由解析器选择其间接依赖；没有完整锁文件时可重复性较弱。
16|结束锁文件选择分支。
17|用项目 Python 执行 download_model.py，下载配置中指定模型；安装脚本不会自动启动 vLLM 或运行 Agent。
''')
add('scripts/test_qwen.py','实际调用本地服务的算术冒烟测试。它验证通信、生成、JSON 结构和一个简单答案，不评价电路能力。','''
1|导入 json，准备写测试结果文件。
2|导入配置读取与日志路径检查。
3|导入统一 API 客户端，保证测试走同一通信代码。
4|导入 obj Schema 辅助函数，构造简单输出结构。
6|定义测试主函数，避免被 pytest 或其他文件导入时立刻连接服务。
7|要求响应是只有 answer 必填整数的对象；additionalProperties 等规则由 obj 自动添加。
8|读取配置、创建本地客户端并发送 19+23 问题；返回值经 ask 内的 JSON 解析与校验后才赋给 answer。
9|检查 answer 字段是否为 42，否则抛 AssertionError 并显示实际回答。
10|只有上面的断言通过才写 status=passed 和实际响应到 logs/api_test.json。
11|在终端打印 PASS 和回答，便于用户快速确认。
13|只有作为主程序执行才运行下面的 main，import 时不触发网络请求。
14|调用 main 开始测试。
''')
add('scripts/test_agents.py','把相同固定资料分别发送给四个角色，验证每个角色能独立响应。它不是完整端到端编排，合成资料也不是实际仿真。','''
1|模块说明：每个角色都调用真实的本地 Qwen API，而不是使用假模型响应。
2|导入 json，用于保存测试回答。
3|导入集中配置读取与项目路径检查。
4|导入 Agent 类，使用与正式系统相同的角色实现。
5|导入 LocalClient 类，用统一 API 路径请求服务。
7|定义主函数，避免被导入时自动测试。
8|读取当前配置，确定本地模型名、端口及设计规格。
9|建立固定六参数示例字典；dict(key=value) 是 Python 建字典的一种写法。
10|开始 payload 输入，包含配置中的目标和固定两级运放拓扑标签。
11|继续输入，加入参数以及明确 backend=mock、synthetic=True 的合成结果标记。
12|手工放入示例指标，闭合 metrics、simulation、payload 三层字典；这里没有运行 MockSimulation 重新计算。
13|建立空的 results 字典，逐个保存角色测试结果。
14|按固定四个角色循环；若将来新增角色，这个列表不会自动更新。
15|为当前角色创建客户端和 Agent，真正调用 run(payload)。只有 run 正常返回时整条赋值才成功，才记录 status=passed。
16|每通过一个角色就把累计结果保存到 logs/agent_tests.json；如果后续角色失败，文件可能只有已通过的一部分，不能单看存在就认为四个都成功。
17|立即打印当前角色 PASS，方便长时间测试时查看进度。
19|主程序入口保护，import 时不执行 main。
20|调用 main，开始四次独立角色测试。
''')
add('scripts/audit_paths.py','只检查项目生成目录与声明的缓存路径，不遍历整个用户主目录或私人文件。这是配置/链接审计，不是内核系统调用跟踪。','''
1|模块说明限定检查对象为项目产物和可写路径，不检查私人目录。
2|导入 json，以便写入机器可读的审计结果。
3|导入 os，用于读取环境变量和遍历目录树。
4|导入 ROOT 与 project_path，复用同样的边界判断。
6|定义主函数，真正执行检查的入口。
7|建立待检查环境变量名列表，先列临时目录和 XDG 目录。
8|续行增加 uv、pip、Hugging Face 的路径变量。
9|续行增加 torch、Triton、CUDA 与 vLLM 缓存变量。
10|续行列出 vLLM 配置、Numba 与 Matplotlib 路径，并结束列表。
11|逐个从 os.environ 读变量，调用 project_path 验证仍在项目内，再转换成字符串记录。未 source env.sh 而缺变量会直接报 KeyError。
12|建立空列表 links，用来记录找到的符号链接。
13|只列本项目创建的目录树，不扫描 .ssh、.aws 或其他私人文件夹。
14|初始化文件计数器为 0。
15|逐个处理白名单中的项目目录。
16|os.walk 遍历该目录；followlinks=False 不沿目录符号链接继续走入潜在外部树。
17|把当前目录的文件数量累计到总数。
18|对本层目录名和文件名都检查，因为符号链接可以指向目录，也可以指向文件。
19|将本层路径和条目名组合成待检查 Path。
20|只对符号链接进入下方分支。
21|resolve 得到该链接最终目标，供边界检查。
22|保存链接本身路径、目标路径和是否位于 ROOT 内的布尔值。
23|用列表推导式筛出所有目标位于项目外的链接，供审阅。
24|开始报告字典：没有外部链接时为 passed，否则 review_required，并附所有配置写入路径。
25|续行记录文件总数、链接总数与外部链接详细列表。
26|报告明确审计范围不是依赖的每一次内核系统调用，避免过度声称已经证明绝无外部写入。
27|写入 logs/path_audit.json，便于以后查看。
28|同时在终端打印报告。
29|存在外部链接则断言失败并显示列表，使命令返回失败状态；没有自动删除或改写任何链接。
31|主程序入口判断。
32|调用 main，执行审计。
''')
add('tests/test_workflow.py','pytest 离线测试。它使用 CPU 和 Mock 工具，不调用模型 API。运行时用项目内 --basetemp 指定测试临时目录。','''
1|导入 pytest 测试框架。
2|导入 ValidationError，供断言某些非法输入必须报错。
3|导入项目路径和配置读取函数，这是测试对象的一部分。
4|导入 MockSimulation，测试合成工具行为。
6|固定一套六参数测试输入，所有测试引用它；后面的修改输入用新字典避免改变这个共享样本。
8|定义名称以 test_ 开头的测试函数，pytest 会自动发现并调用。
9|声明内部代码必须抛 ValueError；如果没有抛出，pytest 会把本项标为失败。
10|尝试访问项目外 ../../tmp/escape，应该被 project_path 拒绝。它不会真正写该外部路径。
12|定义合成来源标记测试；tmp_path 是 pytest 提供的该测试临时目录对象。
13|调用 MockSimulation，使用真实配置中的规格、固定参数以及 op/ac 分析列表，文件写到测试临时目录。
14|断言结果明确是 synthetic 且 real_spice_executed 为假，防止把 Mock 标成真实仿真。
15|对固定输入，合成功耗应接近 0.216；approx 允许合理浮点误差。
16|读取生成网表，要求存在 NOT EXECUTED 字样，确保产物也有未执行标记。
18|定义非法尺寸输入测试。
19|预期工具会抛出 jsonschema 的 ValidationError。
20|复制固定参数并把 compensation_pf 覆盖为 0；Schema 下限 0.1 应拒绝它，而不是发生除零或静默接受。
22|定义参数更新会改变计算结果的测试。
23|创建 MockSimulation 工具实例。
24|先以原始参数运行一次得到 first。
25|再用新字典把 bias_ua 改为 80，其他参数相同，运行得到 second。
26|合成带宽公式与偏置成正比，所以在此固定电容下第二次带宽应是第一次两倍。这验证参数确实进入了计算，不证明真实电路比例关系。
''')
add('pytest.ini','pytest 的项目测试发现设置，避免把 scripts/ 下的日常 API 脚本当成离线测试自动收集。','''
1|声明 ini 文件的 pytest 配置段。
2|让 pytest 默认只从 tests 目录寻找测试；不会因此运行 scripts/test_qwen.py。
''')
add('.venv/bin/activate','uv/virtualenv 自动生成的激活代码，scripts/activate.sh 会 source 它。通常不要手工修改；这里只解释当前 Bash 路径及其他 shell 兼容分支。','''
1|版权注释，标注来自 virtualenv 开发者；不执行任何命令。
2|只有 # 的分隔注释行，没有运行行为。
3|许可证注释开始：授予获取本软件的人免费使用授权。
4|续行说明授权对象包括软件和相关文档。
5|续行将这些内容统称 Software，并说明可以使用。
6|续行列举使用、复制、修改、合并、发布等授权。
7|续行列举分发、再许可、出售副本等授权。
8|续行说明也可允许接收者这样使用，但须遵守条件。
9|提示后面列出许可证条件；这些都是文字注释。
10|注释段落分隔，不影响脚本执行。
11|许可证要求保留版权和许可声明。
12|续行说明完整副本或主要部分中都要保留上述文字。
13|注释段落分隔。
14|免责声明：软件按现状提供，没有保证。
15|续行说明不提供明示或默示保证。
16|续行列出适销性和特定用途适用性等项目。
17|续行包含不侵权保证及作者责任说明。
18|续行说明作者不承担索赔、损害等责任。
19|续行说明包括合同、侵权等不同责任来源。
20|续行结束与软件使用有关的免责声明；这一组注释不是 Python/Agent 逻辑。
22|注释提醒必须从 Bash 用 source 加载，才能修改当前终端环境。
23|注释提醒不能作为普通独立脚本运行后期待父终端生效。
25|判断 SCRIPT_PATH 变量原来是否已被声明；${变量+_} 用来区分未声明与空值，! 对判断取反。
26|若存在就保存旧 SCRIPT_PATH，之后恢复，减少对用户终端变量的影响。
27|fi 结束条件。
29|注释说明接下来获取脚本路径，主要为可迁移环境兼容逻辑服务。
30|检查是否运行于 Bash；${BASH_VERSION:+x} 在其非空时产生 x。
31|Bash 下用 BASH_SOURCE[0] 取得当前被 source 的文件路径。
32|若脚本路径等于 $0，通常意味着直接运行而不是 source。
33|注释解释这一直接运行检测是 Bash 专有的相对可靠方法。
34|向标准错误打印必须 source 的提示；>&2 表示输出到错误通道。
35|以退出码 33 终止错误的直接调用，避免用户误以为已激活。
36|结束直接调用检查。
37|如果不是 Bash，检查是否是 Zsh。
38|Zsh 分支用该 shell 特有表达式取得文件路径；当前 Bash 工作流不会执行此行。
39|再检查是否为 Ksh。
40|Ksh 分支取脚本路径；当前 Bash 不执行该分支。
41|结束 shell 类型分支。
43|定义 deactivate shell 函数，之后用户输入 deactivate 会执行其正文；这里只是定义。
44|删除先前定义的 pydoc 函数，丢弃输出；|| true 避免不存在时的失败中断流程。
46|注释：下面恢复旧环境变量。
47|注释解释用 ${VAR+_} 检测是否声明变量的技巧。
48|若保存过旧 PATH 且值非空，执行恢复。
49|把 PATH 恢复为激活之前的搜索路径。
50|export 让恢复后的 PATH 也传给随后启动的子进程。
51|删除临时备份变量，避免留下旧状态。
52|结束 PATH 恢复分支。
53|检测是否曾保存 PYTHONHOME，包括原来为空的情况。
54|恢复原来的 PYTHONHOME 值；它影响 Python 的基础安装查找，与 HOME 不同。
55|导出恢复后的 PYTHONHOME。
56|删除其备份变量。
57|结束 PYTHONHOME 恢复分支。
59|注释提醒 shell 会缓存命令位置，恢复 PATH 后需要清掉该缓存。
60|续行说明不清缓存可能仍用之前找到的程序。
61|续行结束上述说明。
62|hash -r 清除 shell 命令路径缓存，标准错误丢弃；不删除磁盘上的模型缓存。
64|检查是否保存过旧终端提示符 PS1。
65|恢复原先终端提示符字符串。
66|导出 PS1。
67|清掉提示符备份。
68|结束提示符恢复分支。
70|删除 VIRTUAL_ENV 变量，表示当前不再激活某个虚拟环境。
71|删除 VIRTUAL_ENV_PROMPT 环境名称变量。
72|除非以 nondestructive 参数调用，否则下一步连 deactivate 函数本身也删除。
73|注释中的 Self destruct 指删除这个 shell 函数，不是删除虚拟环境文件。
74|unset -f deactivate 删除函数定义；项目目录和依赖仍在磁盘。
75|结束 nondestructive 判断。
76|右花括号结束 deactivate 函数定义。
78|注释：正式激活前先清除旧激活留下的无关变量。
79|立即调用刚定义的 deactivate，但传 nondestructive 保留函数，以便之后还能退出当前新环境。
81|设置虚拟环境完整路径 /home/xu/.venv；本环境是按当前绝对位置创建的，不是随意移动目录就能自动更新。
82|兼容 Cygwin/MSYS 系统路径转换的条件；本 Linux 系统通常不进入此分支，cygpath 检查仅在条件需要时执行。
83|在上述兼容环境中把路径转成 Unix 风格；当前 Linux 不需要执行。
84|结束路径转换分支。
85|导出 VIRTUAL_ENV，告诉后续工具当前虚拟环境的位置。
87|注释：VIRTUAL_ENV 已确定，脚本路径这个临时变量可以恢复或删除。
88|续行说明这对可迁移环境很重要。
89|检查开头是否保存了旧 SCRIPT_PATH。
90|有旧值就恢复。
91|导出恢复的 SCRIPT_PATH。
92|删除备份变量。
93|若原来没有 SCRIPT_PATH，进入另一分支。
94|删除本脚本临时设置的 SCRIPT_PATH。
95|结束恢复/删除分支。
97|保存当前 PATH，以便将来 deactivate 恢复。
98|把 .venv/bin 放到 PATH 最前面；终端找 python 时先找到项目解释器，这是激活最关键的一步。
99|导出新的命令搜索路径。
101|生成模板留下的固定比较 x != x 恒为假，因此当前实际总是走下面 else；通常不需手改。
102|不执行的分支会把环境提示名设为空，用于某些模板定制情况。
103|当前实际进入 else 分支。
104|用 basename 取 /home/xu/.venv 的最后一级 .venv，作为提示符显示名。
105|结束提示名选择分支。
106|导出 VIRTUAL_ENV_PROMPT。
108|注释：若用户原来设置 PYTHONHOME，需要暂时取消，以免干扰虚拟环境。
109|检查 PYTHONHOME 是否已声明。
110|把旧 PYTHONHOME 值备份下来。
111|unset 暂时移除它，让虚拟环境自己决定 Python 的基础路径。
112|结束 PYTHONHOME 检查。
114|若没有显式禁止改提示符，则进入提示符设置分支。
115|备份原先 PS1，${PS1-} 在变量未设置时给空字符串。
116|在原提示符前面加 (.venv) 等环境名，使用户看出已激活。
117|导出新提示符。
118|结束提示符分支。
120|注释提醒如果 pydoc 是 alias，先取消以免影响后面定义函数。
121|查询并取消已有 pydoc alias，抑制输出和无 alias 时的失败；不删除 Python pydoc 模块。
123|定义新的 pydoc shell 函数。
124|调用当前 PATH 中的 python -m pydoc，并原样传递用户参数，保证查看的是当前环境的文档。
125|结束 pydoc 函数。
127|注释再次解释更新 PATH 后要让 shell 忘记旧命令位置。
128|续行说明不清缓存可能不遵守新 PATH。
129|续行结束说明。
130|清除命令路径缓存并忽略不支持时的错误，激活过程到此结束；不启动模型或 Agent。
''')

if __name__=='__main__':
    out=ROOT/'docs/guide/annotations.json'
    out.write_text(json.dumps(FILES,ensure_ascii=False,indent=2))
    print(f'{len(FILES)} files, {sum(len(v["lines"]) for v in FILES.values())} fully explained source lines -> {out}')
