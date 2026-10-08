# 模拟电路公式手册

每个 agent 每次调用、开始推理前，必须完整阅读本文件。
本文件列符号、公式及适用条件，第 14 节为通用诊断自检；不含具体电路的参数方案。
输入的 derived_calculations 是 Python 对本轮实测预先算好的数值（估算），优先引用，不要心算；仿真实测优先。
公式中的器件/级编号是数学记号，不指向项目中的特定电路。工艺模型与测量值不等同于理想近似。
两级运放出现第二级器件失饱和时，先按第 12 节用实测电流与当前 W/L 算出失配比 Rm 再推理；性能分析先读第 13 节。

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
两器件 cascode 简化输出阻抗：Rout≈ro1+ro2+(gm2+gmb2)*ro1*ro2。
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

## 12. 二极管接法镜像负载的两级运放：级间电流一致性（DC）

记号：镜像参考管 Ma（栅漏相连）、输出管 Mb；第二级共源管 Mg（栅接 Mb 漏）；电流汇 Ms；out 为 Mg、Ms 共漏节点；Ia=Ma 电流=Itail/2；Is=Ms 电流。参数名由 device_dimensions 给出。
F1：输入相同、Mb 饱和时 V(nB)≈V(nA)，故 |VGS_g|≈|VGS_a|，由 Ia 与 (W/L)a 决定，与 (W/L)g 无关。
F2：out 空载时 KCL 强制 Ig=Is；真正的问题是 Mg 在该 VGS 下的能力电流 Ig,cap≈Ia*[(W/L)g/(W/L)a] 是否等于 Is。
失配比 Rm=[(W/L)g/(W/L)a]*(Ia/Is)。Rm>1：Mg 想多供，out 被推向 Mg 侧电源轨，Vsd_g 变小，Mg 进线性区；Rm<1：Ms 先失饱和；Rm≈1 时 out 居中。
Rm 为一阶估算（L、VT(L)、lambda 使平衡点随 L 移动），out 对 Rm 极敏感：先按 (W/L)g_target=(W/L)a*Is/Ia 估值，再按实测 out 偏离中点的方向微调。
增大 (W/L)g 使 Rm 增大，对 Rm>1 只会更糟；降低 Rm 的通道：减小 (W/L)g、增大 Ms 倍率、减小 Itail、增大 (W/L)a（镜像两管须相同）。
仅改 Iref（倍率不变）同比缩放所有电流，Rm 不变，只增加功耗。W↑、L↓ 对 W/L 同向，先算净 W/L。
|VDSAT|≈sqrt(2I/beta)∝1/sqrt(W/L)；M=Vsd−|VDSAT|；Vov=|VGS|−|VT|；两者不同。Vov<0 而 M>0 可以是正常弱反型工作点，是否失败看配置判据，读 dc_acceptance 的具体失败项。
CC、Rz 无 DC 通路，不能修复 DC 失败项。越界提案被拒绝且无新测量。某改动使失败项恶化即方向反了，下一轮换通道。
性能阶段改 (W/L)g、(W/L)a、Itail、Iref、Ms 倍率会移动 Rm，已通过的 DC 可能重新失败；增大 gm2 时与 Ms 成组缩放并重核 out。

## 13. 两级 Miller 运放：增益、带宽、零极点与 PM

A0≈A1*A2；A1≈gm_in/(gds_in+gds_a_out)；A2≈gm_g/(gds_g+gds_s)；gds≈lambda*I，lambda∝1/L：同电流增大 L 提高 gm/gds。
弱反型 gm≈I/(n*UT)，增大 W 几乎不增 gm，只增寄生电容；强反型 gm=sqrt(2*beta*I)，增 W 或 I 均增 gm。用 gm/I 判断位置。
UGB≈gm1/(2*pi*Cc)。Cc 增大使 UGB、RHP 零点 gm_g/Cc 同时下降，p2 上升，PM 净变化需核算；Cc 对 DC 增益无贡献。
几何电阻 R=Rsheet*L/W：L、W 同比放大 R 不变；增大 R 需增大 L 或减小 W。
Miller 模型：omega_u≈Gm1/Cc；omega_p2≈gm_g*Cc/(C1*C2+C1*Cc+C2*Cc)≈gm_g/C2（CL 主导）；无 Rz 零点 s_z=+gm_g/Cc（RHP）。
串联 Rz：omega_z=1/[Cc*(Rz−1/gm_g)]；Rz<1/gm_g 零点仍在 RHP；Rz>1/gm_g 为 LHP；抵消 p2 约 Rz≈1/gm_g+1/(Cc*omega_p2)；Rz*C1 额外极点须远高于 UGB。
PM≈90°−atan(wu/wp2)−atan(wu/wz_RHP)+atan(wu/wz_LHP)−atan(wu/wp3)。仅有 RHP 零点在 UGB 附近时 PM 损失约 30–45°。
增大 p2 的通道是增大 gm_g（并保持第 12 节一致性），不是增大 Cc。
功耗 P≈VDD*(Iref+Itail+Is)；余量可换 gm（UGB、p2）。

## 14. 通用诊断自检

A. 提案前自检，不满足则重写：
1. 写出每个改动的旧值→新值、增/减与倍数；reason 的方向文字必须与之一致。
2. 在边界内（以 target 为准，勿凭印象说“已最大”）；整数参数取整；有效尺寸在器件边界内。
3. 多参数决定的量（R=Rsheet*L/W、W/L、倍率乘积）先算净变化；同比改分子分母等于没改。
4. 用 derived_calculations 的数值预测各指标变化，预测不到的不改。
5. 最多 3 个改动，各有独立机制，避免无法归因。
6. 同参数连续两轮同方向无改善或 A→B→A 振荡：换通道。

B. 工作点：gm/I≈25–30 为弱反型（增 W 不增 gm，只能增 I）；5–15 为中强反型。节点贴近电源轨、某管 Vds 很小，通常是上下两路电流不一致（第 6、12 节），不是 W 太小。

C. 情形→建议：
- 管线性区：比较其能力电流与强制电流并使之相等，改后核对节点是否居中。
- 管截止：查栅偏置来源，不要改其他支路。
- 增益低：看 A1、A2 哪级低，增大该级 L 或 gm。
- UGB 低：减小 Cc 或增大 gm1（增电流）。
- PM 低：先看零点方向（Rz 对 1/gm2）与 p2/UGB；RHP 零点先使其变 LHP；p2<2*UGB 时增大 gm2。
- PM 过大而 UGB 低：减小 Cc，留 5–10° 裕度。
- 功耗超标：降低电流最大的一路并核对 gm、UGB、DC；有余量则用于增 gm。
- 多个缺口：先修使其他指标不可测的 DC 失败或使相位失效的零点；不为一项牺牲已满足项。
- 全部满足：只小步留余量，随后停止。
- 连续无效：检查提案是否被拒绝、是否用了过时的 current_parameters。

公式适用条件是模型定义的一部分；具体器件、环路和测量的符号约定以当前输入为准。
