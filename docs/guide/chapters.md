# 本地 Qwen 与 Multi-Agent：从零开始的完整使用手册

这份手册对应 /home/xu 中实际存在的项目。阅读对象是没有 Python、Agent、API、JSON 或 GPU 使用经验的人。你可以先读第 1—5 章运行系统，再读第 6—9 章理解机制，最后对照逐行附录学习代码。本文的代码修改示例是教学方案，没有自动改动现有 Agent 程序，也没有替换现有模型。

当前已验证的组合是 Python 3.11.13、PyTorch 2.6.0 + CUDA 12.4、vLLM 0.8.5 和 Qwen3-8B。模型加载、API、四个角色独立调用和端到端流程已经实测。电路部分仍然是 Mock，即人为写出的公式产生的合成数据，没有执行真实 SPICE，也没有工艺 PDK。

逐行讲解范围：所有项目自编的运行、启动、停止、下载、安装、测试与路径检查脚本，六个 analog_agents 模块、完整 settings.json、四份提示词，以及实际使用的 .venv/bin/activate 自动生成脚本。空行、注释、括号续行也单独标明。第三方 vLLM、PyTorch、Python 标准库和 NVIDIA 二进制库有海量内部代码，本手册说明其实际入口、位置、输入输出和作用，不声称把这些依赖源码逐行讲完。模型权重是数值文件，不是可逐行解释的 Python 代码。生成 PDF 的排版程序不参与 Agent 运行。

行号取自本次读取的源文件；代码以后有变化时应重新生成手册。附录不是重新编写的伪代码，而是把磁盘中的原始代码逐行摘出解释。PDF 中一条长代码可能视觉上折成几行，左侧 L 编号仍表示源文件的一行。复制修改示例应优先使用 Markdown 源文档，避免 PDF 自动换行破坏缩进。

# 1. 先回答：我到底要运行哪个文件？

## 1.1 最短的可执行步骤

在已经 SSH 登录服务器的终端中，一行一行输入以下命令。不要把这些命令输入 Python 的 >>> 提示符里；它们是交给 Bash 终端执行的。

```bash
cd /home/xu
source scripts/activate.sh
bash scripts/start.sh
bash scripts/test_qwen.sh
bash scripts/run_demo.sh
bash scripts/stop.sh
```

第一行进入项目目录；第二行准备当前终端的 Python 和缓存环境；第三行启动本地模型服务并等待 Ready；第四行检查模型是否能返回 19+23=42；第五行才是真正开始一次四角色 Multi-Agent 实验；最后一行在不再使用模型时停止后台服务。第四行是建议执行的验证步骤，不是 Agent 流程自身的一部分。

你日常真正需要记住的运行入口是 /home/xu/scripts/run_demo.sh。它最终启动的是 /home/xu/analog_agents/run.py 中的 main() 函数。它本身不会启动 Qwen，所以必须先执行 start.sh。你不能只双击 run.py 就期待整个系统自动准备好。

## 1.2 为什么要分成启动服务和运行实验？

Qwen3-8B 权重大约 16 GB。把这些数值从磁盘加载到 GPU 需要时间。start.sh 把模型加载一次，并让后台程序持续等待请求；run_demo.sh 是一个较小的前台程序，每次运行都向这个后台服务发送若干请求，保存一次实验，然后退出。你可以在模型服务仍运行时多次执行 run_demo.sh，不必每次重新加载权重。

run_demo.sh 结束并不等于 GPU 已释放。只有 stop.sh 停止服务后，模型占用的显存才会释放；nvidia-smi 的显示可能需要短暂等待才更新。关掉 Agent 客户端或运行 deactivate 都不会自动停止后台模型。

## 1.3 哪些输出表示成功？

start.sh 先打印 Starting PID ...，稍后打印 Ready: http://127.0.0.1:8000/v1。只看到 Starting 不代表加载完成。test_qwen.sh 成功时打印 Local Qwen API: PASS 和 answer=42。run_demo.sh 会打印 architecture: OK、sizing: OK、simulation 0: MOCK ...，最后给出 Results: /home/xu/outputs/某个时间戳目录。

summary.json 的 status=completed 仅表示程序正常完成了这一轮工作流程，不表示电路合格。是否满足合成目标，要查看 final.simulation.checks 与 all_targets_met_synthetically。real_circuit_validated=false 表示未验证真实电路。出现 Traceback、failure.json 或进程非零退出时，要按错误处理，不可把它当成实验成功。

## 1.4 第二天重新登录后怎么做？

```bash
cd /home/xu
source scripts/activate.sh
nvidia-smi
bash scripts/start.sh
bash scripts/run_demo.sh
bash scripts/stop.sh
```

重新登录会创建新的终端环境，通常要重新 source。系统已经安装，不要每天重新执行 install.sh 或下载模型。如果 start.sh 提示服务已经运行，先确认本项目服务状态；没有必要反复启动同一实例。不要使用 killall python 或 pkill 杀掉共享服务器上的其他任务。

# 2. 零基础概念：这些东西分别是什么？

## 2.1 文件夹、文件、路径与当前目录

/home/xu 是绝对路径，从 Linux 文件系统最上层 / 开始。scripts/run_demo.sh 是相对路径，只有当前目录是 /home/xu 时才指向本项目脚本。cd 改变当前目录；pwd 显示当前目录；ls 列出文件。以点开头的 .venv 和 .runtime 是隐藏目录，不是特殊的远程地址，用 ls -a 可以看到。

.sh 文件装着 Bash 终端指令；.py 文件装着 Python 程序；.json 文件保存有格式的数据；.md 文件保存可阅读的文字；.safetensors 保存模型权重数值；.cir 保存 SPICE 风格的电路连接描述。扩展名帮助人和工具区分用途，但并不保证内容正确。

## 2.2 Python、解释器、库、函数与对象

Python 是一种编程语言。解释器是执行这种语言的软件，在这里从 .venv/bin/python 启动。程序中的 import 表示使用其他模块已有的功能，不是重新安装软件。安装依赖发生在安装阶段；日常 import 只是从本地文件读取并执行模块初始化。

函数是一段有名字、可重复调用的步骤。例如 load_config() 读取配置并返回结果。def 定义函数时，其内部正文还不执行；遇到 main() 或 load_config() 这样的调用时才执行。括号中是传给函数的输入，return 是函数交回的结果。

class 定义一种对象的模板。Agent 是模板，Agent("sizing", client) 创建一个具体的尺寸设计角色对象。self 代表正在使用的那个对象；self.prompt 把该对象自己的提示词存起来。对象不是另一个模型，也不必对应另一个 Linux 进程。

## 2.3 变量、字典、列表与 JSON

变量是给一份数据起名字，例如 params 指向当前电路参数。Python 字典像一张按名称取值的表：params["bias_ua"] 取偏置电流。列表是一串按顺序排列的值，例如 history 保存每次评估记录。列表下标从 0 开始，history[-1] 表示最后一条记录。

```python
params = {"bias_ua": 40, "compensation_pf": 2}
current = params["bias_ua"]
history = []
history.append(params)
```

第一行建立字典；第二行读出 40；第三行建立空列表；第四行把 params 对应对象加入列表。这是 Python 代码，不是终端命令；可以保存到 .py 文件执行，不能直接当成 bash 命令逐行输入。

JSON 是一种把数据写成文本的通用格式。API 通信和输出文件都使用它。JSON 本身不会调用 GPU，也不会执行工作流程。JSON 字段名必须用双引号，布尔值写 true/false，不能写注释，最后一个字段后面不能留多余逗号。

```json
{
  "bias_ua": 40,
  "synthetic": true,
  "analyses": ["op", "ac"]
}
```

Python 中相近的写法是 True/False；json.dumps 把 Python 字典转成 JSON 文本，json.loads 反过来把文本变成字典。Schema 是检查这份数据长什么样的规则，例如 bias_ua 必须是 1—300 之间的数字。Schema 校验能拒绝缺字段和越界参数，却不能证明模型的电路结论正确。

## 2.4 Agent 在这个项目中的准确含义

四个 Agent 是四套角色指令和输出格式，分别负责架构、初始尺寸、仿真计划、参数调整。它们都调用同一个 Qwen3-8B 服务，运行顺序由 run.py 的 Python 代码决定，并不是四个各自自由运行、自动相互聊天的大模型。

系统没有自动训练或更新模型权重，没有长期记忆数据库，也没有自动扫描所有项目文件。模型只看到 client.py 明确传给它的 system 和 user 消息。run.py 保存的 history 不会自动变成模型记忆，必须显式加入下一次请求才能让模型看到。

## 2.5 API、HTTP、客户端和服务端

API 是软件之间约定的“如何提出请求、如何返回结果”。客户端是提出请求的程序，这里是 client.py 加 OpenAI Python SDK。服务端是等待并处理请求的程序，这里是 vLLM 的 api_server.py。HTTP 是它们传递请求的通信协议。

127.0.0.1 是本机回环地址，在服务器上指服务器自己，在你的个人电脑上则指个人电脑自己。8000 是程序监听的端口号，相当于同一台机器上某个服务的入口编号。/v1/chat/completions 是具体接口路径。这个项目使用本机网络接口传消息，但不需要把设计请求发给 OpenAI 云端。

代码使用 from openai import OpenAI，是因为这个 SDK 支持 OpenAI 格式的接口。base_url 明确改成了本机 vLLM；api_key="local-only" 是本地占位字符串，不是真实云端密钥，也不意味着服务已经启用身份认证。同一服务器上能访问该回环端口的其他进程也可能调用它。

## 2.6 GPU、显存、CUDA、PyTorch 和 vLLM

CPU 执行普通控制逻辑，例如读取 JSON、保存文件和计算 Mock 公式。GPU 擅长并行计算大量数值，本项目用它运行 Qwen。显存是 GPU 自己的内存，用于放模型权重、推理中间结果和对话缓存；磁盘里有模型文件，不代表它已经进入显存。

NVIDIA 驱动是系统与 GPU 硬件沟通的软件，当前为 550.144.03。CUDA 运行库提供 GPU 运算所需的基础功能。PyTorch 是张量计算库，vLLM 在它及 CUDA 等组件之上负责高效加载和调用模型。Qwen 是模型架构加权重，不能仅靠一个 .safetensors 文件对外提供 API。

nvidia-smi 显示 CUDA 12.4，说明驱动所支持的 CUDA 版本范围，并不等于安装了同版完整开发工具包。当前 PyTorch 自带的运行库是 CUDA 12.4；系统 PATH 中 nvcc 是 10.1，本项目推理没有依靠这个旧编译器。不要为了本项目修改共享服务器驱动。

GPU=0 指 nvidia-smi 列出的第 0 张卡。脚本通过 CUDA_VISIBLE_DEVICES 让模型进程只看到这一张卡；在进程内部这张卡也编号为 cuda:0。这里四个 Agent 不需要四张卡。gpu_memory_utilization=0.5 是 vLLM 的显存预算比例，不是把 GPU 算力限制在 50%；实测推理时利用率可以达到 95%。

# 3. 所有软件实际安装在哪里？

## 3.1 项目解释器与虚拟环境

虚拟环境的作用是把本项目的 Python 软件包与系统 Python 分开。source scripts/activate.sh 会让当前终端优先找到 .venv/bin 下的 python 等命令，但没有修改 .bashrc 或系统 Python。下面每条路径都对应此次检查的实际安装位置。

| 项目 | 完整位置 | 作用 |
| --- | --- | --- |
| 日常 Python 入口 | /home/xu/.venv/bin/python | 所有项目脚本实际选用的解释器入口 |
| 解释器真正文件 | /home/xu/.runtime/python/cpython-3.11.13-linux-x86_64-gnu/bin/python3.11 | 上述入口解析到的 Python 3.11.13 |
| Python 标准库 | /home/xu/.runtime/python/cpython-3.11.13-linux-x86_64-gnu/lib/python3.11/ | json、pathlib、subprocess 等内置模块 |
| 虚拟环境包目录 | /home/xu/.venv/lib/python3.11/site-packages/ | 本项目安装的第三方库 |
| uv 工具 | /home/xu/.runtime/tools/bin/uv | 安装解释器和依赖，日常推理不必运行 |
| 激活脚本 | /home/xu/.venv/bin/activate | uv 自动生成，由 scripts/activate.sh source |

.venv/bin/python 是指向项目内解释器的链接，而不是另一份完整 Python 拷贝。库安装在 .venv，基础解释器及标准库在 .runtime/python；两者合作完成隔离环境。不要移动其中一个文件夹后期待另一个仍能运行。

## 3.2 运行依赖的精确位置

下表的 P 只是为了让表格容易读，完整前缀为 /home/xu/.venv/lib/python3.11/site-packages。P/torch/ 就是 /home/xu/.venv/lib/python3.11/site-packages/torch/，不是需要你新建的 P 文件夹。

| 软件和版本 | 目录 | 什么时候使用 |
| --- | --- | --- |
| vLLM 0.8.5 | P/vllm/ | start.sh 启动后台模型服务；实际入口 P/vllm/entrypoints/openai/api_server.py |
| PyTorch 2.6.0+cu124 | P/torch/ | 服务加载权重和执行 GPU 张量运算；原生库在 P/torch/lib/ |
| Transformers 4.51.3 | P/transformers/ | 模型配置、分词器及 Qwen 相关支持 |
| Hugging Face Hub 0.30.2 | P/huggingface_hub/ | download_model.py 下载模型；服务可用本地缓存逻辑 |
| OpenAI SDK 1.78.1 | P/openai/ | client.py 发送本地 HTTP 请求 |
| jsonschema 4.26.0 | P/jsonschema/ | 对模型返回字典及仿真参数作结构/范围检查 |
| NVIDIA CUDA 运行库 | P/nvidia/ | GPU 运行依赖；libcudart 位于 cuda_runtime/lib/libcudart.so.12 |
| Triton / xformers / xgrammar 等 | P/triton/、P/xformers/、P/xgrammar/ | vLLM 的计算或结构化输出依赖，由安装器一并解决 |
| ReportLab 4.4.1 | P/reportlab/ | 只在生成 PDF 时使用 |
| pytest 8.3.5 | P/pytest/ 和 P/_pytest/ | 只在运行离线测试时使用 |

P/nvidia/cublas/、cudnn/、nccl/ 等目录提供不同的 GPU 数学/通信库。你通常不需要直接调用它们，服务通过上层库自动加载。全部已安装依赖的版本清单在 requirements.lock；requirements.txt 只列主要直接依赖。改这两个文本文件本身不会立即改变已安装软件。

## 3.3 模型、缓存、日志与系统复用部分

| 内容 | 路径 | 是否软件/数据 |
| --- | --- | --- |
| Qwen3-8B 权重 | /home/xu/models/Qwen3-8B/model-00001-of-00005.safetensors 等五个分片 | 模型数值数据 |
| 权重索引 | /home/xu/models/Qwen3-8B/model.safetensors.index.json | 告诉加载器每个权重在哪个分片 |
| 模型配置 | /home/xu/models/Qwen3-8B/config.json | 模型层数等结构信息；不是项目 settings.json |
| 分词文件 | /home/xu/models/Qwen3-8B/tokenizer.json、tokenizer_config.json、vocab.json、merges.txt | 把文字转换为 token 数字并套用对话模板 |
| 生成默认值 | /home/xu/models/Qwen3-8B/generation_config.json | 模型作者提供的默认生成参数，可能影响未显式设置项 |
| 缓存 | /home/xu/.runtime/cache/ | Hugging Face、uv、PyTorch、Triton、CUDA 等各自子目录 |
| 临时文件 | /home/xu/.runtime/tmp/ | 下载、测试和运行的临时工作位置 |
| 运行记录 | /home/xu/logs/ | 模型日志、服务 PID 信息和验证结果 |
| 实验产物 | /home/xu/outputs/ | 每次实验一个带时间戳的子文件夹 |
| Bash | /usr/bin/bash 或 /bin/bash | 已存在的系统终端解释器，只读复用 |
| NVIDIA 查询工具 | /usr/bin/nvidia-smi | 已存在的系统 GPU 状态工具 |
| NVIDIA 驱动用户库 | /lib/x86_64-linux-gnu/libcuda.so.1 | 系统驱动的一部分，只读复用；内核驱动也由系统管理 |
| Git 2.25.1 | /usr/bin/git | 系统已有工具，当前流程不调用它 |

项目安装的软件、模型和缓存都放在 /home/xu 内，但不是所有硬件支撑软件都重新安装在这里：Bash、系统驱动和 Linux 本来就存在。无需也不应把系统 NVIDIA 驱动复制进项目。没有使用 Conda，也没有安装真实电路仿真器。

查看当前使用的解释器，使用下面命令；输出应指向本项目。which 只查看命令来源，readlink 查看链接最终目标，都不会安装或修改软件。

```bash
cd /home/xu
source scripts/activate.sh
which python
readlink -f .venv/bin/python
python -m pip show torch vllm openai
```

# 4. 想修改什么，就去哪个文件？

| 修改目的 | 修改的项目文件 | 生效时间 |
| --- | --- | --- |
| GPU、端口、模型目录、显存比例、上下文长度 | config/settings.json | 停止旧服务并重新启动 |
| 实验指标、最大迭代次数、temperature、max_tokens、超时 | config/settings.json | 下一次启动 run_demo.sh 时读取 |
| 架构角色指令 | prompts/architecture.md | 下一次创建 Agent 时读取 |
| 尺寸角色指令 | prompts/sizing.md | 同上 |
| 仿真计划角色指令 | prompts/simulation.md | 同上 |
| 优化角色指令 | prompts/optimization.md | 同上 |
| 每个角色输出哪些字段、允许的数值范围 | analog_agents/agents.py | 下一次实验生效；同时更新使用这些字段的代码 |
| 请求发到哪里、消息如何组成、如何处理响应 | analog_agents/client.py | 下一次实验生效 |
| 谁先运行、谁后运行、循环次数与停止条件 | analog_agents/run.py | 下一次实验生效 |
| 网表连接、Mock 公式、仿真工具接入 | analog_agents/simulation.py | 下一次实验生效 |
| 配置合法性检查和根目录限制 | analog_agents/config.py | 下次加载配置时生效 |
| vLLM 的启动参数与进程管理 | scripts/service.py | 下次重启模型服务生效 |
| 下载哪些模型文件 | scripts/download_model.py | 下次主动下载时生效 |
| 缓存/临时路径和环境变量 | scripts/env.sh | 新启动的脚本生效；已有后台进程不变 |
| 依赖版本与重装方式 | requirements.txt、requirements.lock、scripts/install.sh | 真正执行安装命令后生效 |

修改提示词不等于修改角色的程序逻辑。例如提示词写“最多优化十次”，而 run.py/config 中仍限制为 2，程序只会做至多两次参数更新。提示词要求输出新字段，但 agents.py 的 additionalProperties=false 不允许它，响应会被拒绝。模型回答“目标已达成”，也不能覆盖 Python 自己算出的 checks=false。

settings.json 与 models/Qwen3-8B/config.json 是两个完全不同的配置文件。前者由你维护，用于本项目运行；后者是模型仓库文件，描述神经网络架构。不要把 gpu、max_iterations 等项目设置塞进模型目录里的 config.json。

# 5. 从第一条命令到结束：逐个文件追踪 workflow

## 5.1 阶段 A：准备终端环境

你在终端输入 source scripts/activate.sh。Bash 读取 /home/xu/scripts/activate.sh；该文件先通过自己的所在目录定位并 source /home/xu/scripts/env.sh。env.sh 计算 PROJECT_ROOT=/home/xu，设置 TMPDIR、HF_HOME 等变量，确保临时文件与缓存留在项目内，并创建必要目录。

activate.sh 接着 source /home/xu/.venv/bin/activate。这个自动生成文件把 .venv/bin 放到 PATH 前面，设置 VIRTUAL_ENV，并给提示符加上环境名称。此时没有加载 Qwen、没有调用 GPU，也没有执行 Agent。source 的改变发生在当前终端；如果改用 bash scripts/activate.sh，变化只留在短命子进程中，回到原终端时不会完成同样的激活。

## 5.2 阶段 B：启动后台模型服务

B1. bash scripts/start.sh 让 Bash 读取 /home/xu/scripts/start.sh。它启用错误检查，重新 source scripts/env.sh，进入 /home/xu，然后用明确的 .venv/bin/python 执行 scripts/service.py，并把 start 作为命令行参数传入。

B2. Python 加载 service.py 的 import。引用 analog_agents.config 时，会先初始化 analog_agents/__init__.py，再执行 config.py 的顶层代码，确定 ROOT。import 不会自动执行 config.py 中 load_config 的函数正文。service.py 随后定义 birth、owned、stop、start 函数，直到走到文件末尾 __main__ 分支。

B3. service.py 打开 logs/service.lock，用 fcntl.flock 取得非阻塞排他锁。它根据 sys.argv[1] 的 start 选择执行 start()。这把锁防止同一项目的启动/停止管理动作同时修改状态文件；它不是实验室 GPU 资源预约，也不会一直锁住整个后台服务寿命。

B4. start() 调用 config.py 的 load_config()，读取 /home/xu/config/settings.json，解析 JSON，检查 GPU 编号、端口、显存比例、上下文长度、迭代次数与 mock 后端是否合法。它查询 logs/service.json（若存在），避免重复启动自己仍在运行的服务；还尝试绑定 127.0.0.1:8000，检查端口是否空闲。

B5. start() 调用系统 /usr/bin/nvidia-smi，查询所选 GPU 的 UUID、已用显存、总显存和利用率。已用显存大于 1024 MiB 或利用率大于 5% 就抛错退出；没有自动找另一张卡，更不会杀掉占用者。空闲检查与真正占用之间仍可能有别的任务进入，因此共享环境应遵守实验室调度规则。

B6. 它把 settings.json 中 model_dir 解析成 /home/xu/models/Qwen3-8B，先检查模型 config.json 是否存在。这一检查不是对五个权重分片的完整性验证；完整模型能否加载，后面的 vLLM 启动才会真正验证。模型缺失时，start.sh 不会自动下载。

B7. service.py 复制当前环境变量，为子进程设置 CUDA_VISIBLE_DEVICES="0"、CUDA_DEVICE_ORDER="PCI_BUS_ID"、VLLM_USE_V1="0" 和离线模式。然后通过 subprocess.Popen 启动新的后台进程，实际命令入口是 .venv/bin/python -m vllm.entrypoints.openai.api_server。

B8. Python 按模块名找到 /home/xu/.venv/lib/python3.11/site-packages/vllm/entrypoints/openai/api_server.py。从这里进入第三方库内部：vLLM 解析 --model、--host 等参数，读取模型目录下的配置、分词文件、权重索引和五个 safetensors 分片，在 GPU 0 分配显存、加载权重并预热。它通过 PyTorch、CUDA 运行库和系统驱动完成 GPU 运算。这里描述逻辑依赖，不假定库内部并行加载文件的精确先后顺序。

B9. vLLM 监听 127.0.0.1:8000，所有标准输出和报错追加到 logs/qwen.log。service.py 将子进程 PID、进程出生标记、GPU UUID、端口和命令写到 logs/service.json，再反复请求 /health。健康检查返回 HTTP 200 才打印 Ready 并结束启动管理程序。后台模型进程因为 start_new_session=True 仍然继续运行。

## 5.3 阶段 C：一次可选的 API 冒烟测试

bash scripts/test_qwen.sh -> source scripts/env.sh -> .venv/bin/python scripts/test_qwen.py。test_qwen.py 调用 load_config，创建 LocalClient，让模型回答 19+23，并用只允许 answer 整数的 Schema 约束输出。返回值通过校验且 answer==42 后，写 logs/api_test.json。这个测试调用的仍是本地 GPU 模型，不是把固定答案假装成模型响应。

## 5.4 阶段 D：正式运行 Multi-Agent

D1. bash scripts/run_demo.sh 读取同名脚本，准备环境并进入项目目录，然后执行 .venv/bin/python -m analog_agents.run。-m 表示“按照模块名执行”，会正确处理 run.py 中 from .config 等相对导入；直接 python analog_agents/run.py 可能报相对导入错误。

D2. Python 导入 analog_agents/__init__.py 与 run.py 依赖的 config.py、client.py、agents.py、simulation.py。这些导入建立函数、类和 Schema；在这个阶段只定义 Agent，不会自动发起四次模型请求。run.py 最后检测 __name__=="__main__"，然后调用 main()，正式进入实验。

D3. main() 再次读取 config/settings.json。它生成日本时区的时间戳，例如 outputs/20261002-131535-070986/，建立新实验目录，并把本次配置写成该目录下的 config.json。这个输出配置是快照，不是下一次实验的输入；真正的输入仍在项目 config/settings.json。

D4. main() 按 architecture、sizing、simulation、optimization 建立四个 Agent。每创建一个 Agent，就先创建一个 LocalClient(cfg)，再由 Agent.__init__ 读取 prompts/相应角色.md。因此会有四个 Python 客户端对象，但都指向同一个模型服务，不会加载四份权重。Agent 把提示词读入内存一次，本次运行中途修改 .md 通常不会改变已经创建的 Agent。

D5. main() 建立 context={"specification": ...} 和 history=[]。context 是准备给角色看的材料；history 是本地累计的评估记录。最先运行 architecture，它收到设计指标。架构结果写入 context["architecture"] 和 architecture.json。接着 sizing 收到包含指标和架构结果的 context，返回 parameters 和 rationale，写入 sizing.json；从中取出 parameters 作为当前 params。

D6. 进入 for step in range(max_iterations+1)。默认 max_iterations=2，所以 step 可能依次是 0、1、2。step=0 是初始尺寸评估，后两次是允许的参数更新后评估。因此最多三次仿真评估，而不是“总共两次评估”。

D7. 每轮建立 iteration-0 等目录。先调用 simulation Agent，让它看到设计指标、初始架构/尺寸记录，以及顶层 parameters 中的当前尺寸。它返回 analyses 列表和理由。这里顶层 parameters 才是迭代后的当前值；context["sizing"] 仍保留初始设计，程序没有同步覆盖它。

D8. Python 直接调用 simulation.py 中 MockSimulation().run(...)。它校验当前参数，调用 netlist() 从固定模板生成 conceptual_not_executed.cir，再用写死的数学公式计算 metrics，逐项与目标比较得到 checks。它没有读取这个 .cir 去运行 SPICE，也没有调用 ngspice，且这些计算使用 CPU。analyses 的 op/ac/tran 会影响网表中追加哪些分析语句，但当前 Mock 指标仍全部计算，不是分别真正执行这些分析。

D9. run.py 把当前 step、parameters、simulation_plan 和 simulation 组装为 record，加入 history，并覆盖保存完整 history.json。覆盖是为了让文件始终包含当前所有已完成记录，不是只保存最后一轮。由于 record 是字典对象，后续给它增加 optimization 字段，history 中同一个对象也会出现这个字段。

D10. 如果 step 已达到最大迭代次数，立即 break 跳出循环；这一轮不会再调用 optimization Agent。如果未达到，就让 optimization Agent 看到 context 加当前 record：指标、架构、初始尺寸、当前参数、当前 Mock 结果和模拟公式。完整 history 默认没有传入。

D11. 把优化回答记录到 record["optimization"] 并再次保存 history.json。如果 advice["stop"] 为真且程序计算的 all_targets_met_synthetically 也为真，停止循环。两个条件必须同时成立；模型说停，但程序发现未达标时，不会因这条条件停下。

D12. 没有提前停止时，params = advice["parameters"] 把优化建议完整替换为下一轮当前尺寸，然后返回 D7。程序没有自动保留最优方案、没有回滚变差的建议，也没有保证每次建议都不同；同样参数也可能再次评估。

D13. 循环正常结束，保存 summary.json，里面 final=history[-1]。打印 Results 路径后 Python 进程退出。Qwen 后台服务仍在。try 内发生异常时写 failure.json，再 raise 把错误继续向终端抛出；但 main() 开头读取配置、建目录和建 Agent 位于 try 之前，这些早期错误可能只出现终端 Traceback，而没有 failure.json。

## 5.5 每一次 Agent 调用内部，又发生了什么？

Agent.run(context) -> LocalClient.ask(prompt, context, SCHEMAS[name]) -> SDK chat.completions.create(...)。client.py 建立两条消息：system 消息是角色提示词加输出 Schema，user 消息是 context 转成的 JSON 字符串。temperature、max_tokens 等来自 settings.json，enable_thinking=False 关闭 Qwen3 思考输出，guided_json 把结构要求发给 vLLM。

SDK 把请求发送到 http://127.0.0.1:8000/v1/chat/completions。vLLM 用分词器把文字变成 token ID，把它交给已经驻留 GPU 的 Qwen，逐步生成输出 token，再变回文本，并封装 HTTP JSON 响应。请求里不包含任意自动读取的磁盘文件，只有代码显式提供的消息。

client.py 取 response.choices[0]。若 finish_reason 不是 stop，例如达到 token 上限导致 length，就报“输出不完整”。正常时将 message.content 从 JSON 文本解析成 Python 字典，再用 jsonschema.validate 作结构和范围检查。通过后才 return 给 run.py。finish_reason="stop" 是这一次文字生成的结束原因，和 optimization 输出字段 stop=true 是两件不同的事。

一个 request 会等待模型返回后，Python 才执行下一步。当前没有 async、线程池或四角色并发。SDK 的 max_retries=1 表示某些可重试的请求错误会自动再尝试一次；timeout_seconds 是 SDK 网络超时设置，不能理解为整个实验严格在 180 秒内完成。

## 5.6 阶段 E：停止模型服务

bash scripts/stop.sh -> source env.sh -> .venv/bin/python scripts/service.py stop。service.py 读取 logs/service.json，借助 /proc/进程号/stat 比较进程出生标记，避免只按可能被复用的 PID 杀进程。确认属于已记录进程后，用 os.killpg 向该进程组发 SIGTERM，请它正常退出。

脚本最多轮询约 30 秒，检测进程退出或进入僵尸状态，然后删除服务状态文件；日志文件和模型权重不会删除。CUDA 显存释放可能在 nvidia-smi 中稍后才显示。脚本不会执行卸载、不清除 outputs，也不会替你退出虚拟环境。如果想取消当前终端的环境激活，另输入 deactivate。

# 6. 一次实际数据如何在文件和内存之间流动？

下面的示例来自已有实验 outputs/20261002-131535-070986/，不是本次编写手册重新运行的结果。初始参数 input_w_um=20、input_l_um=1、bias_ua=40、compensation_pf=2。Mock 初始增益为 60.612 dB、带宽 16 MHz、相位裕度 68 度、功耗 0.216 mW。

优化返回 input_w_um=25、bias_ua=35，其他字段保持。run.py 中 params = advice["parameters"] 让下一次仿真真正使用这些新值，于是 Mock 增益变为 61.775 dB、带宽 14 MHz、功耗 0.189 mW。目标增益是 65 dB，仍未达到，所以虽然 summary.status 是 completed，final.simulation.checks.gain_db 仍是 false。

这说明软件完成了“取建议、应用、重新计算”的闭环，不说明电路完成了优化。当前只保存最后一次评估作为 final，并没有挑选历史最优。如果未来某次建议使结果更差，也会照样保存在最后一轮；第 8 章说明如何修改这些逻辑。

| 文件 | 谁写入 | 什么时候看 |
| --- | --- | --- |
| config.json（实验目录内） | run.py 的 save | 确认这次实验用了什么设置 |
| architecture.json | run.py | 查看架构角色原始回答 |
| sizing.json | run.py | 查看初始参数与理由，不是最终参数 |
| history.json | run.py，每轮至少写一次 | 查看所有已完成评估和优化建议 |
| iteration-N/conceptual_not_executed.cir | simulation.py | 检查第 N 轮概念连接和数值；未执行 |
| summary.json | run.py，正常结束后 | 查看最终评估及 workflow 完成状态 |
| failure.json | run.py 的异常分支 | 查看 try 内失败原因；不是所有早期失败都能写入 |
| logs/qwen.log | 后台 vLLM 进程 | 查模型加载、API、显存和服务错误 |

不要改 outputs 内的 JSON 期待影响下一次运行：那是历史记录。修改输入请改 config/settings.json、prompts 或 analog_agents 中的代码。history.json 中出现一个字段，并不意味着它自动参与下一次请求；要看 client.ask 的 payload 究竟来自哪个字典。

# 7. 不改 Python 也能完成的设置调整

先备份要改的文件，再编辑。在下面示例中，备份保存在项目 docs/ 下。文件名用不同版本避免覆盖你想保留的旧备份。

```bash
cd /home/xu
cp config/settings.json docs/settings.before-edit.json
nano config/settings.json
```

nano 是终端文本编辑器；若系统没有安装，可用你已经使用的 VS Code Remote 编辑同一文件。保存后运行以下命令检查 JSON 语法；这只检查是否能解析，不会启动模型。

```bash
source scripts/activate.sh
python -m json.tool config/settings.json
python -c 'from analog_agents.config import load_config; print(load_config())'
```

## 7.1 改实验指标和迭代次数

把 settings.json 中的 "max_iterations": 2 替换为 "max_iterations": 4，就允许最多五次评估和四次优化建议。config.py 当前限制为 1—10，超过 10 需要同时改校验，不是改 JSON 一个数字就能生效。把 specification 中 "gain_db_min": 65 替换为 "gain_db_min": 60，会改变 Python 判断目标达成的门槛，而不是改变 Mock 公式。

把 "temperature": 0.2 改成 0.1 可减少生成的随机性，但不保证每次完全相同。把 "max_tokens": 1200 改成 1800，允许单次模型回答更长；输入加输出仍要放进 context_length，回答越长也可能越慢。

## 7.2 改卡号、端口和上下文

例如先确认 GPU 1 空闲，再把 "gpu": 0 替换为 "gpu": 1。把 "port": 8000 替换为 "port": 8001，会同时影响下次启动的服务和下次创建的 LocalClient，因为两者都读同一份配置。先 stop.sh，再修改，再 start.sh，避免后台仍在旧端口而客户端已经访问新端口。

context_length=8192 是输入与输出总 token 容量；max_tokens=1200 是单次输出上限。二者不同。gpu_memory_utilization=0.5 不要随意改到 1：当前校验最多允许 0.6，且共享服务器不应无确认占满设备。

## 7.3 改角色提示词

prompts/ 中每个文件是一段 system 指令，名字要与 agents.py/run.py 中的角色名称对应。可以把尺寸角色要求改为“说明每项参数的假设”，但仍要遵守规定 JSON 字段。改提示词不需要重启 Qwen；重新运行 run_demo.sh 会创建新 Agent 并读取新文本。

# 8. Python 层面如何修改：逐项给出原语句和替换语句

本章示例以当前源码为起点，彼此独立。不要不加判断把所有示例同时叠加。除非明确标为完整替换，代码块只是指定位置的一段，应保留原有缩进。四个空格表示一级 Python 代码块，缩进不同会改变逻辑或引起错误。示例没有自动应用到生产文件；后面的示例验证记录会说明检查到什么程度。

## 8.1 让 Agent 达标后直接停止，不依赖模型同意

当前 run.py 在得到 optimization 回答后判断：

```python
            if advice["stop"] and result["all_targets_met_synthetically"]:
                break
```

如果你的目标是“只要当前评估已满足所有合成指标，就连优化请求都不再发送”，应将下面这一段插入到 if step == cfg["max_iterations"]: 之前：

```python
            if result["all_targets_met_synthetically"]:
                break
```

原来的双条件判断可以保留，它在这个改法中对于达标场景已经不会再执行。新增判断的位置很重要：如果放在调用 optimization 之后，只能省掉下一轮评估，不能省掉这次模型请求。此修改依然只判断 Mock 指标，不会把 Mock 变为真实电路验证。

## 8.2 把历史记录也传给优化 Agent

当前 run.py 的原语句是：

```python
            advice = agents["optimization"].run({**context, **record})
```

替换为：

```python
            advice = agents["optimization"].run({
                **context,
                **record,
                "previous_iterations": history[:-1],
            })
```

**context 表示把 context 的键值展开到新字典；后面的同名键会覆盖前面的值。history[:-1] 是不包含本轮的旧记录列表，避免把本轮内容重复发送。这个字典马上被 json.dumps 转成文本发给模型，不会形成无限循环引用。更多历史会占用更多 token，可能要减少记录内容或调整上下文，而不是无限堆积。

## 8.3 让每个角色使用不同 temperature

第一步，在 settings.json 的 "temperature": 0.2 后添加一个字段，记得逗号：

```json
  "agent_temperatures": {
    "architecture": 0.3,
    "sizing": 0.1,
    "simulation": 0.1,
    "optimization": 0.1
  },
```

第二步，在 agents.py 中找到 def run(self, context): 及其下一行，完整替换这个方法：

```python
    def run(self, context):
        temp = self.client.config.get("agent_temperatures", {}).get(
            self.name, self.client.config["temperature"])
        return self.client.ask(
            self.prompt, context, SCHEMAS[self.name], temperature=temp)
```

第三步，在 client.py 中把函数头 def ask(self, prompt, payload, schema): 替换为：

```python
    def ask(self, prompt, payload, schema, temperature=None):
```

同一函数内，把 temperature=self.config["temperature"], max_tokens=self.config["max_tokens"], 这一整行替换为：

```python
            temperature=(self.config["temperature"] if temperature is None else temperature),
            max_tokens=self.config["max_tokens"],
```

.get(key, default) 表示字段不存在就使用默认值，这样 test_qwen.py 仍然可以不传角色温度调用 ask。None 表示“没有指定”，而不是 0；温度 0 是一个有效的明确值，不能用 if temperature 误判为未提供。这三处必须配套，否则可能出现“ask 不接受 temperature 参数”的错误。

## 8.4 在仿真前增加一个 Review Agent

这不是简单加一份 prompt 就能运行；必须增加输出 Schema、创建对象并在流程里调用它。先创建 prompts/review.md，内容如下：

```text
You are a review agent. Check the proposed parameters against the given
specification and identify conceptual issues. No PDK is available.
Return approved (boolean) and reason (string) as JSON.
Do not claim real circuit validation. Be concise in Chinese.
```

在 agents.py 的 SCHEMAS 字典内，给 optimization 所在字段末尾加逗号，再加入：

```python
    "review": obj({"approved": {"type": "boolean"}, "reason": TEXT}),
```

在 run.py 中，把创建 agents 的原语句替换为：

```python
    agents = {
        name: Agent(name, LocalClient(cfg))
        for name in ("architecture", "sizing", "simulation", "optimization", "review")
    }
```

在 run.py 循环中 step_dir.mkdir() 之后、plan = agents["simulation"].run(...) 之前，插入：

```python
            review = agents["review"].run({**context, "parameters": params})
            save(f"review-{step}.json", review)
            if not review["approved"]:
                raise ValueError("Review rejected: " + review["reason"])
```

这样每轮当前参数都会先经过 review，拒绝时触发已有 failure.json 路径，不会继续做本轮仿真。approved 是模型意见，仍不是电路安全证明。test_agents.py 的固定四角色列表不会自动扩展；若想五角色独立测试，还应把该脚本列表补上 review。本例只是在“仿真前”插入一关，不能把 sizing 放到 architecture 之前，因为 sizing 本来依赖架构结果。

## 8.5 用确定性 Python 规则代替模型的优化建议

如果先想学清楚“改一个参数如何影响后面”，可以暂时用一条可理解的规则替换优化模型调用。只替换 run.py 中 advice = agents["optimization"].run({**context, **record}) 这一行，换成下面整段：

```python
            next_params = dict(params)
            needed_ratio = 10 ** ((cfg["specification"]["gain_db_min"] - 45) / 12)
            next_params["input_w_um"] = min(
                200.0,
                max(params["input_w_um"], needed_ratio * params["input_l_um"] * 1.02),
            )
            advice = {
                "parameters": next_params,
                "rationale": "Synthetic formula rule; not a physical circuit optimizer.",
                "stop": result["all_targets_met_synthetically"],
            }
```

dict(params) 建一个独立字典，避免直接改掉历史记录中旧参数；needed_ratio 是把 Mock 增益公式反解后的最小 W/L；乘 1.02 留少许数值余量；min(200.0, ...) 保持当前 Schema 中输入管宽度上限。其他参数沿用当前值，之后原代码会记录 advice、更新 params、重新计算。

这个例子不再让 Optimization Agent 调模型，虽然原来的对象仍被创建。它只针对现有 Mock 增益公式，不能用于真实晶体管设计，也不能保证所有目标或所有输入都可达。它用于理解 Python 控制流程与“模型建议”可以替换成不同算法。

## 8.6 扩大参数范围时，改哪里？

agents.py 的 PARAMETERS 决定模型尺寸和优化输出允许的范围。原字段：

```python
    "input_w_um": {"type": "number", "minimum": 1, "maximum": 200},
```

例如在你确认实验需要后，可替换为：

```python
    "input_w_um": {"type": "number", "minimum": 1, "maximum": 300},
```

sizing 和 optimization 的 Schema 都引用同一个 PARAMETERS，所以它们会一起使用新上限；simulation.py 的 validate 也引用它。但如果你同时采用 8.5 的规则，那里 min(200.0, ...) 还会额外限制为 200，也要有意修改成 300.0。JSON Schema 的修改不会自动寻找并替换其他文件里的数字。

新增参数比改上限更复杂：不仅要加 Schema，还要决定提示词、网表、公式和使用方如何读取。当前 netlist() 用 PARAMETERS 字段顺序解包成六个变量，贸然增加第七个字段会发生“解包值过多”。下一节给出先消除这一隐式依赖的改法。

## 8.7 修改 netlist 参数读取方式，避免依赖字典顺序

在 simulation.py 中，把下面的原语句：

```python
    w, l, load, stage, bias, cc = [p[k] for k in PARAMETERS["properties"]]
```

替换为：

```python
    w = p["input_w_um"]
    l = p["input_l_um"]
    load = p["load_w_um"]
    stage = p["stage2_w_um"]
    bias = p["bias_ua"]
    cc = p["compensation_pf"]
```

原代码依赖 PARAMETERS 中六个字段的插入顺序；改成按名字读取更容易理解，也不会因为字典重排把晶体管宽度误当成电流。这仍然没有实现任何新的电路参数，只是先把参数与网表的对应关系写得明确。

## 8.8 真正接入电路仿真器，需要改动哪些层？

当前 config.py 明确 assert simulation_backend == "mock"，run.py 又直接写 MockSimulation().run(...)。因此单把 JSON 改成 "ngspice" 会立即失败；把 assert 删除而不改 run.py，则仍在跑 Mock，不能这样冒充接入成功。

可以先做一个诚实的工厂函数，为未来真实实现留入口。在 simulation.py 文件末尾新增：

```python
def make_simulator(backend):
    if backend == "mock":
        return MockSimulation()
    raise NotImplementedError(
        "This backend has no validated simulator implementation yet: " + backend)
```

在 run.py 中，把 from .simulation import MockSimulation 替换为 from .simulation import make_simulator；把 result = MockSimulation().run(params, cfg["specification"], plan["analyses"], step_dir) 替换为：

```python
            result = make_simulator(cfg["simulation_backend"]).run(
                params, cfg["specification"], plan["analyses"], step_dir)
```

这一步保持原有 mock 限制和结果，不会自动安装仿真器。未来必须实现真实类：受控生成带合适模型的网表；用固定可执行文件、shell=False 和 timeout 运行仿真器；检查退出码、输出文件、收敛情况；解析带单位的数值；与指标比较；只有成功才返回 real_spice_executed=true。失败必须报错，不能偷偷用 Mock 数字补齐。

本项目没有 PDK、真实仿真器安装路径或经过验证的指标提取脚本，所以此处不能给出一条“把 X 换成 Y 就完成真实电路仿真”的虚假承诺。替换工具调用、物理模型和结果解析是不同工作，完成后还要有真实仿真测试。现有 LEVEL=1 概念网表不能代替工艺模型。

## 8.9 如何检查你改过的 Python？

先做语法检查，不启动 GPU、不导入你修改的业务模块：

```bash
cd /home/xu
source scripts/activate.sh
python - <<'PY'
import ast
from pathlib import Path
for folder in ("analog_agents", "scripts"):
    for path in Path(folder).glob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
        print("syntax OK", path)
PY
python -m pytest -q --basetemp="$TMPDIR/pytest"
```

ast.parse 能发现缺冒号、括号不配对或缩进语法问题，但不能保证算法正确。现有四项测试覆盖参数拒绝、Mock 标签等，不会替你自动验证新角色。之后再启动服务、执行 test_qwen.sh、test_agents.py、run_demo.sh，并检查新 outputs。文档示例通过语法检查不等于已经做过真实 GPU 集成测试。

# 9. 如何更新模型，而不把几个“版本”混为一谈？

## 9.1 先区分四件事

模型仓库 model_repo 是模型名字，例如 Qwen/Qwen3-8B；model_revision 是仓库内某一快照的 commit；model_dir 是下载到本机的目录；served_model 是 API 对外报出的别名。它们不是 vLLM 软件版本，也不是 Python 版本。

更新同一仓库权重快照、从 8B 换成 4B、升级 vLLM 推理框架，是三种不同操作。改 served_model 只改接口名字，不会使 GPU 自动加载另一个模型。服务使用 --model 指定的本地目录；离线模式下它不会自动替你追踪远程最新版本。

## 9.2 同一个 Qwen3-8B 仓库，取得新的固定快照

先停止旧服务并备份配置。下面命令只作为你日后主动更新时的完整做法，本次手册重写没有运行这个下载或替换操作。获取 main 的当前 SHA 需要联网；如果 main 仍是原来的 SHA，就没有新快照，不需要反复下载。

```bash
cd /home/xu
source scripts/activate.sh
bash scripts/stop.sh
cp config/settings.json docs/settings.before-model-update.json
python - <<'PY'
import json
from pathlib import Path
from huggingface_hub import HfApi
path = Path("config/settings.json")
cfg = json.loads(path.read_text())
new_sha = HfApi().model_info(cfg["model_repo"], revision="main").sha
if new_sha == cfg["model_revision"]:
    print("Already using this revision:", new_sha)
else:
    cfg["model_revision"] = new_sha
    cfg["model_dir"] = "models/Qwen3-8B-" + new_sha[:12]
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    print("New pinned revision:", new_sha)
PY
python scripts/download_model.py
bash scripts/start.sh
bash scripts/test_qwen.sh
python scripts/test_agents.py
bash scripts/run_demo.sh
```

HfApi().model_info 只查询仓库元信息，.sha 取当前 main 指向的固定提交值；真正下载由下一条 download_model.py 完成。cfg["model_dir"] 改为新目录，避免把不同快照的文件混放，也保留旧版本用于回退。字符串 [:12] 取提交号前十二个字符作为目录后缀，完整 revision 仍保存完整提交号。

同一仓库 revision 也不保证永远与旧软件完全兼容，仍需实际加载验证。新目录可能再占约一份模型的磁盘空间，应先 df -h /home/xu。本机磁盘是共享资源，不要按首次部署的空闲量假定以后一直足够。

## 9.3 从 Qwen3-8B 换成 Qwen3-4B 的完整配置更新示例

这是可选的较小同系列模型示例，不是“最新模型”推荐，也没有在此服务器重新下载测试。Qwen 官方模型卡说明 Qwen3-4B 支持 Transformers 4.51+、vLLM 0.8.5+；最终能否在你当前环境工作仍以实际测试为准。参考：https://huggingface.co/Qwen/Qwen3-4B 。

```bash
cd /home/xu
source scripts/activate.sh
bash scripts/stop.sh
cp config/settings.json docs/settings.before-4b.json
python - <<'PY'
import json
from pathlib import Path
from huggingface_hub import HfApi
path = Path("config/settings.json")
cfg = json.loads(path.read_text())
repo = "Qwen/Qwen3-4B"
sha = HfApi().model_info(repo, revision="main").sha
cfg.update(
    model_repo=repo,
    model_revision=sha,
    model_dir="models/Qwen3-4B-" + sha[:12],
    served_model="qwen3-4b-local",
)
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
PY
python scripts/download_model.py
bash scripts/start.sh
bash scripts/test_qwen.sh
python scripts/test_agents.py
bash scripts/run_demo.sh
```

这里被替换的四项分别是原 model_repo="Qwen/Qwen3-8B"、旧的 model_revision、model_dir="models/Qwen3-8B"、served_model="qwen3-8b-local"。没有让你手填一个未经验证的 commit；脚本查询真实存在的快照再固定它。

## 9.4 换成别的模型家族时，Python 哪些地方可能要改？

service.py 的 cmd 列表控制 --dtype bfloat16、上下文、推理后端等；不同模型可能不支持当前设置。client.py 的 extra_body 里 chat_template_kwargs.enable_thinking 是 Qwen3 的对话模板约定，不能假定任何模型都支持。对没有这个选项、但仍支持 guided_json 的模型，可把原语句：

```python
            extra_body={"chat_template_kwargs": {"enable_thinking": False}, "guided_json": schema})
```

替换为：

```python
            extra_body={"guided_json": schema})
```

这个条件式示例只移除 Qwen 特有的模板参数，不保证新模型已被旧 vLLM 支持。也不建议在当前 Qwen3 模型上随意移除，因为默认思考内容可能影响纯 JSON 返回和 token 长度。若要启用 Qwen 思考模式，不能只把 False 改 True 就宣布完成：需正确处理 reasoning 与最终答案分离、预算和结构化输出兼容性。

模型的内置 chat template 位于 tokenizer_config.json 等模型文件，由服务自动使用。当前程序没有单独的 prompt template 引擎；prompts/*.md 只是角色内容。换家族时先阅读该模型官方卡、服务版本的支持列表，再决定配置和代码修改，不能由一个 model_repo 字符串解决全部兼容问题。

## 9.5 升级 vLLM 或 PyTorch，应该修改哪里？

requirements.txt 中的 vllm==0.8.5 是直接依赖声明；requirements.lock 中也固定了 vllm 及其大量间接依赖。install.sh 优先读取 requirements.lock，所以只改 requirements.txt 再运行 install.sh，仍会装锁文件中的旧版本。service.py 的命令行参数、client.py 的 guided_json 参数也可能随推理版本变化，需要一起核对。

没有一个可对任意未来版本照抄的“把 0.8.5 改成最新版”方案：新框架可能要求高于现有驱动的 CUDA。这里保留已验证版本。可在项目内新建测试环境，不覆盖 .venv：

```bash
cd /home/xu
source scripts/activate.sh
.runtime/tools/bin/uv venv --python 3.11.13 .venv-trial
```

然后为你已查证兼容的目标版本建立 requirements.trial.txt，使用 uv pip install --python .venv-trial/bin/python -r requirements.trial.txt 安装。具体版本必须根据当时官方兼容说明选定，本手册不猜测未来版本。不要把这一命令当成已完成升级。要让启动和实验脚本使用测试环境，还需把对应 .sh 中 "$PROJECT_ROOT/.venv/bin/python" 明确换为 "$PROJECT_ROOT/.venv-trial/bin/python"；activate.sh 中的 .venv/bin/activate 也需要配套调整。

确认试验环境通过 GPU、API 和端到端测试后，才导出该环境自己的 pip freeze --all 清单作为新的锁文件；不要从旧环境导出后误认为锁住新版本。若测试环境没有 pip，可用 .runtime/tools/bin/uv pip freeze --python .venv-trial/bin/python 导出。全程不得通过升级系统驱动解决兼容性问题。

## 9.6 模型切换失败如何回退？

```bash
cd /home/xu
source scripts/activate.sh
bash scripts/stop.sh
cp docs/settings.before-4b.json config/settings.json
bash scripts/start.sh
bash scripts/test_qwen.sh
```

上例对应 9.3 的备份文件；如果你做的是 9.2，应使用 settings.before-model-update.json。旧权重目录仍在，因此恢复配置后可以重新加载原模型。不要删除旧权重再测试新模型，否则回退可能还要重新下载。

# 10. 遇到问题，按文件定位

| 现象 | 优先看哪里 | 含义与下一步 |
| --- | --- | --- |
| No module named ... | which python；.venv；requirements.lock | 可能没有使用项目解释器，先 source activate.sh |
| attempted relative import ... | run_demo.sh、run.py 启动方式 | 使用 -m analog_agents.run，不要直接运行包内文件路径 |
| JSONDecodeError | settings.json 或模型 message.content | 配置语法错误或回答不是完整 JSON；区分发生在哪个 json.loads |
| ValidationError | agents.py 的 SCHEMAS、原始参数 | 缺字段、类型不符或超出范围；不是 GPU 坏了 |
| Connection error | logs/qwen.log、端口配置 | 模型未启动、已崩溃、端口不一致，或工具沙盒限制 |
| GPU is busy | service.py 查询结果、nvidia-smi | 当前卡有其他任务；等待或选择已确认空闲的卡 |
| Model absent | model_dir/config.json | 尚未下载到配置指定目录，或路径写错 |
| Incomplete model output: length | client.py、max_tokens | 模型输出到达长度上限；可能需减少输入或增加合理预算 |
| Context length exceeded | context_length 与请求历史大小 | 过多历史或长提示词；减小 payload 或调整容量 |
| summary completed 但 gain_db=false | history.json、Mock 公式 | 流程结束而目标未达，不是成功标志互相矛盾 |
| 改 prompt 没变化 | prompts 的文件名、当前进程 | 已创建的 Agent 使用内存文本；重新运行实验 |
| 改 port 后无法连接 | service.py 与 client.py 的配置读取时机 | 旧服务仍监听旧端口；停止再启动 |

检查文件可使用 cat 查看较短 JSON，tail 查看日志末尾。不要把未知网络教程中的 sudo、全局 pip、全局 CUDA 升级或 killall 命令直接复制到共享服务器。这里只需围绕项目脚本和已知日志定位。

```bash
cd /home/xu
tail -n 80 logs/qwen.log
cat logs/verification.json
cat outputs/20261002-131535-070986/summary.json
```

# 11. 如何阅读后面的逐行附录

每个文件先说明它的角色和被谁调用，然后列出原始行号、原始代码与中文解释。缩进是 Python 语法的一部分；括号未闭合时，同一条语句可以跨越多行，不能把某个续行单独执行。空行没有执行动作，但用于分组；# 后的内容通常是注释；三引号在某些位置是说明字符串，在 netlist() 中则是需要返回的多行电路文本。

import、def、class 之后的执行时机不同：模块被 import 时顶层 import/赋值会执行，def 的函数正文等到被调用才执行。if __name__ == "__main__" 避免模块被别人导入时自动运行整个程序。for 遍历一组值；if 分支选择下一步；break 退出循环；try/except 捕获并记录错误；raise 让错误继续中断当前任务。

本附录还逐行解释自动生成的激活脚本、安装/下载辅助流程和离线测试。这些代码不是每次实验都全部执行。例如 install.sh、download_model.py 只在安装或主动更新时用；pytest 测试不调用 Qwen；build_guide.py 只生成文档，不属于被解释的 Agent workflow。

已部署的 API/Agent/GPU 测试证据仍在 logs/verification.json；本次只更新文档及文档生成工具，没有重新运行 GPU 实验。修改示例的静态/局部验证会单独记录，不能替代你实际改代码后的集成测试。
