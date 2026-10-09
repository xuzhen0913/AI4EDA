# 模拟电路公式手册

尺寸优化 agent 的通用公式与判据：符号、公式及适用条件，第 14 节为通用诊断自检。不含具体电路的参数方案。
公式中的器件/级编号是数学记号，不指向项目中的特定电路。工艺模型与测量值不等同于理想近似。
某节点上的器件失饱和时，先按第 12 节比较“强制电流”与“能力电流”再推理；增益、带宽、功耗与电压余量的通用估算见第 13 节。

## 1. 单位、定义与基本定律

omega=2*pi*f；s 为拉普拉斯变量；UT=kB*T/q，T 用 K；300 K 时 UT≈25.85 mV。
电压增益 dB=20*log10(abs(Av))；功率比 dB=10*log10(P2/P1)。
相位 deg=rad*180/pi。SPICE m=1e-3、u=1e-6、n=1e-9、p=1e-12、meg=1e6。
W/L 无量纲；W、L 的实际单位由网表和 PDK 定义。
KCL：sum(i)=0；KVL：sum(v)=0；瞬时功率 p=v*i（被动符号约定）。

## 2. 无源器件与阻抗

电阻：v=Ri；G=1/R；均匀薄膜 R≈Rsheet*L/W；接触电阻另计。
电容：q=Cv，i=C*dv/dt，ZC=1/(sC)，E=Cv²/2；理想稳态 DC 下 iC=0。
电感：v=L*di/dt，ZL=sL，E=Li²/2；互感 M=k*sqrt(L1*L2)。
串联 RC：Z=R+1/(sC)，Y=sC/(1+sRC)，DC 导纳为零（有限 R、无漏电）。
并联导纳相加，串联阻抗相加。
无负载电阻分压：Vout/Vin=R2/(R1+R2)；有负载时下臂为 R2||RL。
RC 低通 H=1/(1+sRC)；高通 H=sRC/(1+sRC)；omega_p=1/(RC)。
LC：omega0=1/sqrt(LC)；串联 RLC 的 Q=omega0*L/R；并联 RLC 的 Q=R/(omega0*L)。
实体器件的频率、温度、电压系数与寄生由模型决定。

## 3. MOS 电压、工作区与电流

I=abs(Id)，VT=abs(Vth)，beta=mu*Cox*(W/L)。
NMOS：Vg=VG−VS，Vd=VD−VS；PMOS：Vg=VS−VG，Vd=VS−VD。
Vov=Vg−VT；模型饱和裕量 M=Vd−abs(VDSAT)。
DeltaM=DeltaVd−Delta(abs(VDSAT))。Vov 和 M 是不同量。
M<0 表示未满足 Vd>=abs(VDSAT) 判据；overdrive 判据取决于配置阈值。

长沟道、强反型、忽略沟道调制：
- 线性区 0<=Vd<Vov：I=beta*(Vov*Vd−Vd²/2)。
- 饱和区 Vd>=Vov>0：I=beta*Vov²/2，理想 VDSAT=Vov。
- 饱和式重排：Vov=sqrt(2*I/beta)，W/L=2*I/(mu*Cox*Vov²)。
- 线性区小 Vd：Ron≈1/(beta*Vov)。

含一阶沟道调制：I≈beta*Vov²*(1+lambda*Vd)/2（饱和近似）。
NMOS 体效应：Vth=Vth0+gamma*(sqrt(2*phiF+VSB)−sqrt(2*phiF))，phiF 取正幅值。
弱反型近似：I≈I0*(W/L)*exp((Vg−VT)/(n*UT))*(1−exp(−Vd/UT))。
在 Vd 足够大时 gm/I≈1/(n*UT)；Vov<=0 不等于 I=0。
短沟道的速度饱和、迁移率退化、DIBL 等不包含在平方律中；模型 VDSAT 未必等于 Vov。

## 4. MOS 小信号与电容

gm=partial(Id)/partial(VGS)，gds=partial(Id)/partial(VDS)，gmb=partial(Id)/partial(VBS)，
均在指定工作点及其余端电压固定的条件下定义；符号依器件/电流约定。
NMOS 小信号 id=gm*vgs+gmb*vbs+gds*vds；ro=1/gds。
长沟道饱和、忽略 lambda：gm=beta*Vov=2*I/Vov=sqrt(2*beta*I)，gm/I=2/Vov。
一阶 ro≈1/(lambda*I)；NMOS gmb/gm≈gamma/[2*sqrt(2*phiF+VSB)]。
本征增益≈gm/gds；fT≈gm/[2*pi*(Cgs+Cgd)]（简化短路电流增益模型）。
长沟道准静态强反型饱和：内在 Cgs≈(2/3)*W*L*Cox，内在 Cgd≈0；重叠电容另计。
线性区小 VDS：内在 Cgs≈Cgd≈W*L*Cox/2。
结电容近似 Cj(VR)=Cj0/(1+VR/Phi)^m，底面积和侧壁分量各有系数。

## 5. 二极管与 BJT

二极管 I=Is*(exp(V/(n*UT))−1)；正向大电流相对 Is 时 rd≈n*UT/I。
正向有源 BJT：Ic≈Is*exp(VBE/UT)*(1+VCE/VA)，gm≈Ic/UT，
rpi≈betaF/gm，ro≈VA/Ic，alphaF=betaF/(betaF+1)。
扩散电容近似 Cdiff≈tauF*gm；结电容按其反偏模型。
BJT 的截止/正向有源/饱和由 PN 结偏置确定，不是 MOS 的 VDSAT 判据。

## 6. 偏置、电流镜与节点方程

同型、同栅压、相似体偏置、均饱和的理想镜像：
Iout/Iref≈(W/L)out/(W/L)ref。
含一阶沟道调制时再乘 (1+lambda_out*Vd_out)/(1+lambda_ref*Vd_ref)。
若 Wout=N*Wref 且 L 相同，理想镜像比为 N；N 在此表示几何倍率。
多个镜像输出的电源总电流包括参考支路和所有输出支路。
匹配差分对零差分时 I1=I2≈Itail/2，小信号 deltaI1≈gm*vid/2，deltaI2≈−gm*vid/2。
差分输出电流跨导≈gm；单端跨导由实际负载和镜像连接决定。

上下拉共节点静态 KCL：Iup(Vout,...)=Idown(Vout,...)+Iload(Vout,...)。
固定其他节点、局部导纳为正的小信号近似：
deltaVout≈(deltaIup_at_fixed_Vout−deltaIdown_at_fixed_Vout)/(gup+gdown+gload)。
上下堆叠器件的必要电压窗口示例：VS_lower+Vd_required_lower<=Vout<=VS_upper−Vd_required_upper。
一般非线性电路 F(v,p)=0 的局部灵敏度：dv/dp=−(partialF/partialv)^−1*(partialF/partialp)，
要求雅可比可逆；p 是参数向量，v 是节点电压向量。

## 7. 基本放大级

共源/共射：Av≈−gm*Rout；简单有源负载 Rout≈ro_driver||ro_load||RL。
源跟随器：Av≈gm/(gm+gmb+gload)，为简化模型。
源退化、忽略 ro/体效应时：Gm_eff≈gm/(1+gm*Rs)。
简单共栅输入电阻≈1/(gm+gmb)，受偏置与外部连接影响。
级联且负载已计入时：Atotal=product(Ai)。
差模/共模：vid=vip−vin，vicm=(vip+vin)/2；CMRR=abs(Ad/Acm)，CMRR_dB=20log10(CMRR)。
PSRR 的分子、分母依测量定义，常用 abs(Ad/Asupply)；单位及归一化需按 testbench。

## 8. 反馈、极点、零点与时间响应

负反馈约定：Acl=A/(1+A*B)，环路增益 T=A*B，灵敏度 S=1/(1+T)。
单极点 H=A0/(1+s/omega_p)，fp=omega_p/(2*pi)。
单位环路交越 abs(T(j*omega_c))=1；PM=180deg+arg(T(j*omega_c))，相位需正确展开。
相位交越 arg(T)=-180deg 时 GM=1/abs(T)，GM_dB=-20log10(abs(T))。
多次交越及非最小相位系统需完整环路分析；PM 不等于所有闭环稳定性的充分证明。
LHP 极点相位贡献 −atan(omega/omega_p)，LHP 零点 +atan(omega/omega_z)，RHP 零点 −atan(omega/omega_z)。
二阶分母 s²+2*zeta*omega_n*s+omega_n²；Q=1/(2*zeta)。
0<zeta<1 时阶跃超调比 exp(−pi*zeta/sqrt(1−zeta²))。
单极点线性建立：误差比例 exp(−t/tau)，t_epsilon=tau*ln(1/epsilon)。
电容节点 dV/dt=Inet/C；电流受限时 SR≈abs(Iavailable)/C，正负方向可不同。

## 9. Miller 等效与串联 R-C 补偿

跨接局部输入输出的电容 C，局部增益 a=vo/vi：Cin=C*(1−a)，Cout=C*(1−1/a)。
a 为频率相关复数时，等效量也为频率相关；这不是任意频率下的固定电容替换。

以下是常规高增益、极点分裂两级 Miller 模型，Gm1 为前级有效跨导，gm2 为后级信号跨导；
R1/R2 为节点电阻，C1/C2 为两节点对地电容（不含 Cc）：
omega_u≈Gm1/Cc；omega_p1≈1/[R1*(C1+Cc*(1+gm2*R2))]。
omega_p2≈gm2*Cc/(C1*C2+C1*Cc+C2*Cc)，C1 项可忽略时≈gm2/C2。
无串联电阻的前馈零点 s_z≈+gm2/Cc（RHP）；omega_u/omega_z≈Gm1/gm2。
单主极点占优、另一个极点和 RHP 零点时：
PM≈90deg−atan(omega_u/omega_p2)−atan(omega_u/omega_z)，atan 用角度。

串联电阻 Rz 的简化零点：s_z≈1/[Cc*(1/gm2−Rz)]。
Rz<1/gm2：RHP；Rz=1/gm2：该近似零点在无穷远；Rz>1/gm2：LHP。
LHP 情况 omega_z≈1/[Cc*(Rz−1/gm2)]。
在 omega_z=omega_p 的代数条件下 Rz≈1/gm2+1/(Cc*omega_p)。
串联电阻还可能产生额外极点；在相关简化模型中量级约 1/(Rz*C1)。
这些式子不含所有寄生、负载变化或多环路作用。

## 10. 功率、噪声与失配

平均功率 P=average(sum(vk*ik))，电流方向采用一致符号约定。
理想单电源静态近似 P=VDD*Itotal；电容完整充放电周期电源能量≈C*(DeltaV)²。
单边热噪声 PSD：电阻 Sv=4*kB*T*R，Si=4*kB*T/R。
MOS 饱和沟道噪声近似 Si=4*kB*T*gamma_noise*gm；单管输入等效 Sv≈4*kB*T*gamma_noise/gm。
散粒噪声 Si=2*q*I；MOS 闪烁噪声 Sv∝1/(W*L*f^alpha)，具体系数/归一化以模型为准。
输出总噪声：Sout=sum(abs(Hi)²*Si)+交叉相关项；方差=integral(Sout(f)*df)。
理想充分建立的采样电容噪声方差≈kB*T/C。
Pelgrom 近似：sigma(DeltaVT)=AVT/sqrt(W*L)，sigma(DeltaBeta/Beta)=Abeta/sqrt(W*L)。
固定栅压、小失配：DeltaI/I≈DeltaBeta/Beta−(gm/I)*DeltaVT；相关性和空间梯度另计。
器件尺寸公式不包含布局失配、可靠性或制造良率的完整模型。

## 11. 采样、失真与常用指标

理想 N 位量化步长 Delta=FS/2^N，均匀量化误差方差 Delta²/12。
理想满幅正弦 ADC：SNR≈6.02*N+1.76 dB；ENOB=(SINAD_dB−1.76)/6.02，条件同该定义。
THD=sqrt(sum(Vharmonic_rms²))/Vfundamental_rms；THD_dB=20log10(THD)。
采样保持/开关网络的周期稳态不等同于普通 DC OP。

## 12. 节点电流一致性（DC 工作点的通用判断）

任意节点的静态 KCL 要求流入等于流出。节点上若有“被电流源/镜像强制”的支路，其电流 Iforced 不由本节点电压决定；
另一支路的器件栅压若由别处（二极管接法参考管、镜像、固定偏置电压）决定，则它在该栅压下有“能力电流”Icap。
Icap 与 Iforced 不一致时，节点电压不会停在中间：它被推向使二者相等的方向，直到某个器件进入线性区（Vd<|VDSAT|）或截止。
一阶估算：若器件 Mg 的栅压 VGS 与参考管 Ma 相同（同型、同源极电位、均饱和），则
Icap,g ≈ Iref,a*[(W/L)g/(W/L)a]（含沟道调制时再乘 (1+lambda_g*Vd_g)/(1+lambda_a*Vd_a)）。
失配比 Rm = Icap/Iforced：Rm>1 则节点被推向 Mg 所接的电源轨、Mg 失饱和；Rm<1 则强制支路器件先失饱和；Rm≈1 时节点居中。
Rm 是一阶估算（L、VT(L)、lambda 使平衡点随 L 移动），节点电压对 Rm 极敏感：先按目标 W/L 估值，再按实测节点偏离方向微调。
按同一倍率缩放参考电流和所有镜像输出不改变 Rm，只改变功耗；调整 W、L 对 W/L 同向，先算净 W/L。
|VDSAT|≈sqrt(2I/beta)∝1/sqrt(W/L)。Vov<0 而 M>0 可以是正常弱反型工作点，是否失败看判据，读 devices 表的 failed_checks。
无 DC 通路的元件（电容、与电容串联的电阻）不能修复 DC 失败项。某改动使失败项恶化即方向反了，下一轮换通道。
性能阶段改变任何影响上述电流比例的参数，已通过的 DC 可能重新失败，改后须重核节点电压。

## 13. 增益、带宽、功耗与电压余量的通用估算

多级增益 A0≈product(Ai)；每级 Ai≈Gm_i*Rout_i；Rout 为该节点向各支路看进去的电阻并联；gds≈lambda*I，lambda∝1/L：同电流增大 L 提高 gm/gds。
Cascode 堆栈（自输出节点向内，两器件时即 Rout≈ro1+ro2+gm2*ro1*ro2）：R_stack=r_top+R_below+gm_top*r_top*R_below，r=1/gds；并联支路的 gds 相加；体效应使 gm 取 gm+gmb。
输出电阻越大增益越高，但堆栈中任一器件失饱和都会使其对 R 的贡献塌缩。
弱反型 gm≈I/(n*UT)，增大 W 几乎不增 gm，只增寄生电容；强反型 gm=sqrt(2*beta*I)，增 W 或 I 均增 gm。用 gm/I 判断位置。
单级（单主极点、输出节点电容 CL 主导）：UGB≈Gm/(2*pi*CL)，PM 由非主极点 p_nd（如 cascode 内部节点 p≈gm_c/C_node）决定：
PM≈90°−atan(UGB/p_nd)−…；负载电容既设定 UGB 也提供补偿。多级则需第 8、9 节的补偿。
电压余量：同一支路自电源到地的器件须满足 sum(Vds_i)+(其余压降)=VDD 且每个器件 Vds_i>=|VDSAT_i|；
堆叠 n 个器件的最小供电≈sum(|VDSAT_i|)+各级栅源偏置带来的额外压降；堆得越高，输入共模范围和输出摆幅越小。
由固定偏置电压设置的电流：强反型 I≈beta*(VGbias−VS−VT)²/2；偏置电压、W/L 与 VS 共同决定电流，改任何一个都会移动该支路及其上堆叠器件的 Vds。
Cascode 栅偏置的选择：使被它偏置的器件在其源极电位下 Vds 刚好大于 |VDSAT|，同时不压缩下方器件的余量。
功耗 P≈VDD*(各电源支路电流之和)；有余量时可换 gm（UGB、非主极点）。

## 14. 通用诊断自检

A. 提案前自检，不满足则重写：
1. 写出每个改动的旧值→新值、增/减与倍数；reason 的方向文字必须与之一致。
2. 在边界内（以 target 为准，勿凭印象说“已最大”）；整数参数取整；有效尺寸在器件边界内。
3. 多参数决定的量（R=Rsheet*L/W、W/L、倍率乘积）先算净变化；同比改分子分母等于没改。
4. 用 derived_calculations 的数值预测各指标变化，预测不到的不改。
5. 各改动有独立机制，避免无法归因。
6. 同参数连续两轮同方向无改善或 A→B→A 振荡：换通道。

B. 工作点：gm/I≈25–30 为弱反型，5–15 为中强反型（第 13 节）。节点贴近电源轨、某管 Vds 很小，通常是上下两路电流不一致（第 6、12 节），不是 W 太小。

C. 情形→建议（电路的具体通道以 reference 的说明为准）：
- 管线性区：比较其能力电流与强制电流并使之相等，改后核对节点是否居中。
- 管截止：查栅偏置来源（偏置电压/镜像参考），不要改其他支路。
- 整条堆栈的管子同时失败、节点电压贴近某一电源轨：先怀疑偏置电压或电流支路，使整条支路有电流，再逐级核对 Vds。
- 增益低：看各级 Gm*Rout，增大贡献最小的一级的 L 或 gm；堆栈中有管子失饱和时先恢复饱和。
- UGB 低：增大输入级 gm（增电流或 W/L）或减小决定 UGB 的电容。
- PM 低：先识别非主极点与零点的位置，使其远离 UGB；有补偿元件时按第 9 节核算，无补偿元件时减小负载电容或增大非主极点所在节点的 gm。
- PM 过大而 UGB 低：把裕量换成带宽，留 5–10° 裕度。
- 功耗超标：降低电流最大的一路并核对 gm、UGB、DC；有余量则用于增 gm。
- 多个缺口：先修使其他指标不可测的 DC 失败或使相位失效的零点；不为一项牺牲已满足项。
- 全部满足：只小步留余量，随后停止。
- 连续无效：检查提案是否被拒绝、是否用了过时的 current_parameters。

公式适用条件是模型定义的一部分；具体器件、环路和测量的符号约定以当前输入为准。
