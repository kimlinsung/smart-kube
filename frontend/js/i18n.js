// 简单的客户端 i18n：
// - 默认英文，localStorage 持久化语言选择
// - 通过 data-i18n / data-i18n-html / data-i18n-attr 属性声明翻译点
// - 暴露 window.I18N = { t, setLang, getLang, applyI18n, onChange }
(function () {
  'use strict';

  var STORAGE_KEY  = 'site_lang';
  var DEFAULT_LANG = 'en';
  var SUPPORTED    = ['en', 'zh'];

  var DICT = {
    en: {
      /* -- shared -- */
      'brand': 'Cloud-Edge-IoT Multi-Agent Testbed',
      'nav.overview': 'Overview',
      'nav.devices':  'Devices',
      'nav.login':    'Sign In',
      'foot.copy':    '© Cloud-Edge-IoT Multi-Agent Testbed · For research and educational use only',
      'foot.account': 'Account requests:',

      /* -- welcome page -- */
      'welcome.title':            'Cloud-Edge-IoT Multi-Agent Testbed',
      'welcome.hero.tag':         'Testbed Online · Continuously Running',
      'welcome.hero.title':       'A Cloud-Edge-IoT Testbed<br/>for Multi-Agent Research',
      'welcome.hero.subtitle':    'Heterogeneous Cloud-Edge-IoT Infrastructure for Multi-Agent Systems',
      'welcome.hero.lead':        'Targeting frontiers including multi-agent systems, collaborative inference, edge AI and embodied intelligence, this testbed unifies heterogeneous compute across x86, ARM64 and RISC-V instruction set architectures under a single scheduling plane. It covers cloud-side HPC GPU servers, edge-side AI accelerators and device-side robots / MCUs / IoT hardware, providing an end-to-end environment for reproducible multi-agent experiments.',
      'welcome.btn.view_devices': 'View Device Status',
      'welcome.btn.login':        'Sign in to Console',

      'welcome.topo.cloud.servers': 'HPC / GPU Servers',
      'welcome.topo.cloud.isa':     'Instruction Set',
      'welcome.topo.edge.nodes':    'Edge Nodes',
      'welcome.topo.edge.isa':      '+ RISC-V',
      'welcome.topo.iot.devices':   'IoT Devices',
      'welcome.topo.iot.robot':     'Robotics',
      'welcome.topo.iot.mcu':       'MCU / Sensors',

      'welcome.metric.total': 'Total Devices',
      'welcome.metric.cloud': 'Cloud Nodes',
      'welcome.metric.edge':  'Edge Nodes',
      'welcome.metric.iot':   'IoT Devices',

      'welcome.section.cap':         'CAPABILITIES',
      'welcome.section.cap.heading': 'A unified experimental environment built for multi-agent research',
      'welcome.section.cap.sub':     'The testbed exposes heterogeneous hardware as containerised, schedulable units. Researchers can compose experiments across cloud, edge and device tiers, launch them with a single click, attach via in-browser SSH, upload scripts and orchestrate runs through a conversational agent.',

      'welcome.feature.1.title': 'Unified scheduling for heterogeneous compute',
      'welcome.feature.1.desc':  'A unified scheduling plane orchestrates experiment units across x86, ARM64 and RISC-V instruction sets, with fine-grained allocation of GPU / NPU accelerators.',
      'welcome.feature.2.title': 'Multi-agent collaborative experiments',
      'welcome.feature.2.desc':  'First-class support for multi-agent orchestration. Deploy collaborative workloads across cloud-edge-device tiers and validate distributed inference, federated learning and swarm-intelligence paradigms.',
      'welcome.feature.3.title': 'In-browser Web Shell',
      'welcome.feature.3.desc':  'No local setup required — open an interactive SSH terminal for any experiment unit directly in the browser, with file upload and audited operations out of the box.',
      'welcome.feature.4.title': 'Conversational experiment orchestration',
      'welcome.feature.4.desc':  'A built-in agent for operations and experiment orchestration. Drive resource requests, image selection, topology composition and log inspection through natural language.',
      'welcome.feature.5.title': 'Multi-tenant isolation and auditing',
      'welcome.feature.5.desc':  'Per-account and per-experiment isolation with full operation auditing. Administrators can cordon / uncordon nodes and manage user authorisation and quotas at a fine granularity.',
      'welcome.feature.6.title': 'Embodied intelligence & IoT in the loop',
      'welcome.feature.6.desc':  'Covers ROS mobile robots, depth cameras, MCU sensors and smart-home devices — real device-side hardware for closed-loop embodied and edge-device collaborative experiments.',

      'welcome.section.arch':         'ARCHITECTURE',
      'welcome.section.arch.heading': 'A three-tier, integrated compute stack',
      'welcome.section.arch.sub':     'Resources are organised along the canonical cloud-edge-device hierarchy. Each tier complements the others in instruction set, power envelope, latency and functional role, and can be flexibly composed into realistic collaborative topologies.',

      'welcome.layer.cloud.tag':    'CLOUD',
      'welcome.layer.cloud.title':  'High-performance training & inference',
      'welcome.layer.cloud.desc':   'A cluster of x86_64 HPC GPU servers that hosts large-model training, batch inference and control-plane services, providing a stable central compute foundation.',
      'welcome.layer.cloud.nodes':  'Nodes',
      'welcome.layer.cloud.isa':    'ISA · x86_64',

      'welcome.layer.edge.tag':     'EDGE',
      'welcome.layer.edge.title':   'Low-latency accelerator nodes',
      'welcome.layer.edge.desc':    'A multi-architecture edge tier combining NVIDIA Jetson family devices and RISC-V SBCs, spanning ARM64 and RISC-V 64 instruction sets, dedicated to near-field inference and collaborative tasks.',
      'welcome.layer.edge.nodes':   'Nodes',
      'welcome.layer.edge.isa':     'ISA · ARM64 / RISC-V',

      'welcome.layer.iot.tag':      'IoT',
      'welcome.layer.iot.title':    'Embodied intelligence & sensing endpoints',
      'welcome.layer.iot.desc':     'Mobile and quadruped robots, depth cameras, MCUs and smart-home devices covering ARM, AVR and MSP430 micro-architectures — a realistic device-side experimentation environment.',
      'welcome.layer.iot.devices':  'Devices',
      'welcome.layer.iot.kind':     'Robotics / MCU / Sensors',

      'welcome.cta.title':       'Start your multi-agent experiment',
      'welcome.cta.desc':        'Check the live status of available devices, or sign in to the console to compose your own experiment.',
      'welcome.cta.btn.devices': 'Device Status Overview',
      'welcome.cta.btn.login':   'Go to Sign-in Page',

      /* -- devices page -- */
      'devices.title':         'Device Status · Cloud-Edge-IoT Multi-Agent Testbed',
      'devices.crumb.home':    'Home',
      'devices.crumb.current': 'Device Status',
      'devices.page.heading':  'Device Status Overview',
      'devices.page.sub':      'A complete inventory of the cloud-edge-device devices currently available on the testbed, including category, model, instruction-set architecture, discrete-GPU configuration, count and online status.',

      'devices.sum.total':     'Total Devices',
      'devices.sum.cloud':     'Cloud · Cloud Nodes',
      'devices.sum.edge':      'Edge · Edge Nodes',
      'devices.sum.iot':       'IoT · IoT Devices',
      'devices.sum.dot.all':   'All',
      'devices.sum.dot.cloud': 'Cld',
      'devices.sum.dot.edge':  'Edg',
      'devices.sum.dot.iot':   'IoT',

      'devices.note':        'This page is a public view. Data is served by a static endpoint and never touches the cluster. Selected IoT endpoints (cameras, relays, MCUs, smart-home devices, sensors) display count only.',
      'devices.panel.title': 'Device Inventory',
      'devices.panel.live':  'Live',

      'devices.col.category': 'Category',
      'devices.col.device':   'Device',
      'devices.col.isa':      'ISA',
      'devices.col.gpu':      'Discrete GPU',
      'devices.col.count':    'Count',
      'devices.col.online':   'Online',
      'devices.col.status':   'Status',

      'devices.cat.cloud':     'Cloud',
      'devices.cat.edge':      'Edge',
      'devices.cat.iot':       'IoT',
      'devices.gpu.yes':       '✓ Yes',
      'devices.gpu.no':        '— No',
      'devices.status.online': 'Online',
      'devices.status.na':     'Count only',
      'devices.empty.loading': 'Loading…',
      'devices.empty.none':    'No device data',
      'devices.err.load':      'Failed to load device status: ',

      /* -- login page -- */
      'login.title':             'Smart Cloud-Edge-Device Scheduling · Sign In',
      'login.back':              'Back to Home',
      'login.h1':                'Smart Cloud-Edge-Device Scheduling',
      'login.subtitle':          'Cloud · Edge · Device · Unified Scheduling',
      'login.label.username':    'Username',
      'login.label.password':    'Password',
      'login.ph.username':       'admin',
      'login.ph.password':       'admin123',
      'login.btn':               'Sign In',
      'login.feishu.divider':    'or',
      'login.feishu.btn':        'Sign in with Feishu',
      'login.feishu.err_prefix': 'Feishu sign-in failed: ',
      'login.temp.title':        'Request a temporary account',
      'login.temp.body':         'Platform accounts are created by administrators upon review. To request a <b>temporary account</b> for research, teaching or evaluation purposes, please email <a href="mailto:cppcan@163.com?subject=Temporary%20Account%20Request%20for%20Cloud-Edge-IoT%20Testbed&body=Name%2FAffiliation%3A%0APurpose%3A%0AExpected%20duration%3A%0AContact%3A%0A">cppcan@163.com</a> with a brief description of your intended use and time frame.'
    },

    zh: {
      'brand': '云边端多智能体实验床',
      'nav.overview': '概览',
      'nav.devices':  '设备状态',
      'nav.login':    '登录控制台',
      'foot.copy':    '© 云边端多智能体实验床 · 仅用于科研与教学用途',
      'foot.account': '账号开通请联系',

      'welcome.title':            '云边端多智能体实验床',
      'welcome.hero.tag':         '实验床在线 · 持续运行中',
      'welcome.hero.title':       '面向多智能体协同的<br/>云-边-端一体化实验床',
      'welcome.hero.subtitle':    'A Heterogeneous Cloud-Edge-IoT Testbed for Multi-Agent Research',
      'welcome.hero.lead':        '面向智能体系统、协同推理、边缘 AI 与具身智能等前沿方向，本实验床在统一的调度面下，汇聚 x86、ARM64、RISC-V 等多指令集架构的异构算力，覆盖云端高性能 GPU 服务器、边缘 AI 加速节点与端侧机器人 / MCU / IoT 设备，为可复现的多智能体实验提供端到端环境。',
      'welcome.btn.view_devices': '查看设备状态',
      'welcome.btn.login':        '登录控制台',

      'welcome.topo.cloud.servers': 'HPC / GPU 服务器',
      'welcome.topo.cloud.isa':     '指令集',
      'welcome.topo.edge.nodes':    '边缘节点',
      'welcome.topo.edge.isa':      '+ RISC-V',
      'welcome.topo.iot.devices':   '端侧设备',
      'welcome.topo.iot.robot':     '机器人',
      'welcome.topo.iot.mcu':       'MCU / 传感器',

      'welcome.metric.total': '设备总数',
      'welcome.metric.cloud': '云端节点',
      'welcome.metric.edge':  '边缘节点',
      'welcome.metric.iot':   '端侧设备',

      'welcome.section.cap':         'CAPABILITIES',
      'welcome.section.cap.heading': '为多智能体研究而生的统一实验环境',
      'welcome.section.cap.sub':     '实验床以容器化的方式将异构算力抽象为统一的可调度单元，研究者可在浏览器内创建跨云-边-端的实验组合，一键拉起、SSH 接入、上传脚本并通过对话式智能体编排实验。',

      'welcome.feature.1.title': '异构算力统一调度',
      'welcome.feature.1.desc':  '统一的调度面，跨 x86、ARM64、RISC-V 多种指令集架构编排实验单元，支持 GPU / NPU 加速节点的细粒度分配。',
      'welcome.feature.2.title': '多智能体协同实验',
      'welcome.feature.2.desc':  '原生支持多智能体（Multi-Agent）编排，可跨云-边-端节点部署协同任务，验证分布式推理、联邦学习、群体智能等典型范式。',
      'welcome.feature.3.title': '浏览器内 Web Shell',
      'welcome.feature.3.desc':  '无需本地配置，直接在浏览器中获得每个实验单元的交互式 SSH 终端，配合文件上传与日志审计，研究过程开箱即用。',
      'welcome.feature.4.title': '对话式实验编排',
      'welcome.feature.4.desc':  '内置面向运维与实验编排的对话智能体，自然语言驱动资源申请、镜像选择、实验拓扑构建与日志巡检。',
      'welcome.feature.5.title': '多租户隔离与审计',
      'welcome.feature.5.desc':  '账号体系与实验维度的资源隔离，操作全程审计；管理员可对节点 cordon / uncordon、对用户授权与配额进行精细管控。',
      'welcome.feature.6.title': '具身智能与 IoT 实景',
      'welcome.feature.6.desc':  '覆盖 ROS 移动机器人、深度相机、MCU 传感器与智能家居设备等真实端侧硬件，支持具身智能与边-端协同闭环实验。',

      'welcome.section.arch':         'ARCHITECTURE',
      'welcome.section.arch.heading': '三层分级 · 一体化算力栈',
      'welcome.section.arch.sub':     '实验床按典型云-边-端三层结构组织算力资源，各层在指令集、能耗、时延与功能定位上互补，可灵活组合形成真实的协同实验拓扑。',

      'welcome.layer.cloud.tag':   'CLOUD · 云',
      'welcome.layer.cloud.title': '高性能训练与推理',
      'welcome.layer.cloud.desc':  'x86_64 架构的 HPC GPU 服务器集群，承载大模型训练、批量推理与控制面服务，提供稳定的中心算力底座。',
      'welcome.layer.cloud.nodes': '节点',
      'welcome.layer.cloud.isa':   'ISA · x86_64',

      'welcome.layer.edge.tag':    'EDGE · 边',
      'welcome.layer.edge.title':  '低时延加速节点',
      'welcome.layer.edge.desc':   'NVIDIA Jetson 系列与 RISC-V SBC 共同构成的多架构边缘层，覆盖 ARM64 与 RISC-V 64 指令集，承担近场推理与协同任务。',
      'welcome.layer.edge.nodes':  '节点',
      'welcome.layer.edge.isa':    'ISA · ARM64 / RISC-V',

      'welcome.layer.iot.tag':     'IoT · 端',
      'welcome.layer.iot.title':   '具身智能与传感末端',
      'welcome.layer.iot.desc':    '移动机器人、四足机器人、深度相机、MCU 与智能家居设备，覆盖 ARM、AVR、MSP430 等微体系结构，构成真实的端侧实验环境。',
      'welcome.layer.iot.devices': '设备',
      'welcome.layer.iot.kind':    '机器人 / MCU / 传感器',

      'welcome.cta.title':       '开启你的多智能体实验',
      'welcome.cta.desc':        '查看可用设备的实时状态，或登录控制台创建专属实验组合。',
      'welcome.cta.btn.devices': '设备状态总览',
      'welcome.cta.btn.login':   '进入登录页',

      'devices.title':         '设备状态 · 云边端多智能体实验床',
      'devices.crumb.home':    '首页',
      'devices.crumb.current': '设备状态',
      'devices.page.heading':  '设备状态总览',
      'devices.page.sub':      '实验床当前可用的云-边-端设备清单，包括分类、机型、指令集架构、独立 GPU 配置、设备数量与在线情况。',

      'devices.sum.total':     '设备总数',
      'devices.sum.cloud':     'Cloud · 云端节点',
      'devices.sum.edge':      'Edge · 边缘节点',
      'devices.sum.iot':       'IoT · 端侧设备',
      'devices.sum.dot.all':   '全部',
      'devices.sum.dot.cloud': '云',
      'devices.sum.dot.edge':  '边',
      'devices.sum.dot.iot':   '端',

      'devices.note':        '本页面为对外展示视图，数据由公开接口返回，不直接访问集群，部分 IoT 末端设备（相机、继电器、MCU、智能家居、传感器）仅展示数量。',
      'devices.panel.title': '设备清单',
      'devices.panel.live':  '实时',

      'devices.col.category': '分类',
      'devices.col.device':   '设备类型',
      'devices.col.isa':      '指令集架构',
      'devices.col.gpu':      '独立 GPU',
      'devices.col.count':    '数量',
      'devices.col.online':   '在线数量',
      'devices.col.status':   '状态',

      'devices.cat.cloud':     '云 · Cloud',
      'devices.cat.edge':      '边 · Edge',
      'devices.cat.iot':       '端 · IoT',
      'devices.gpu.yes':       '✓ 有',
      'devices.gpu.no':        '— 无',
      'devices.status.online': '在线',
      'devices.status.na':     '仅计数',
      'devices.empty.loading': '加载中…',
      'devices.empty.none':    '暂无设备数据',
      'devices.err.load':      '加载设备状态失败：',

      'login.title':             '智能云边端调度系统 · 登录',
      'login.back':              '返回欢迎页',
      'login.h1':                '智能云边端调度系统',
      'login.subtitle':          'Cloud · Edge · Device · Unified Scheduling',
      'login.label.username':    '用户名',
      'login.label.password':    '密码',
      'login.ph.username':       'admin',
      'login.ph.password':       'admin123',
      'login.btn':               '登录',
      'login.feishu.divider':    '或',
      'login.feishu.btn':        '使用飞书登录',
      'login.feishu.err_prefix': '飞书登录失败：',
      'login.temp.title':        '申请临时账号',
      'login.temp.body':         '平台账号由管理员审核创建。如需用于科研、教学或评测的<b>临时账号</b>，请发送邮件至 <a href="mailto:cppcan@163.com?subject=%E7%94%B3%E8%AF%B7%E4%BA%91%E8%BE%B9%E7%AB%AF%E5%AE%9E%E9%AA%8C%E5%BA%8A%E4%B8%B4%E6%97%B6%E8%B4%A6%E5%8F%B7&body=%E5%A7%93%E5%90%8D%2F%E5%8D%95%E4%BD%8D%EF%BC%9A%0A%E7%94%A8%E9%80%94%EF%BC%9A%0A%E9%A2%84%E8%AE%A1%E4%BD%BF%E7%94%A8%E6%97%B6%E9%97%B4%EF%BC%9A%0A%E8%81%94%E7%B3%BB%E6%96%B9%E5%BC%8F%EF%BC%9A%0A">cppcan@163.com</a>，并简要说明使用用途与时段。'
    }
  };

  function getLang() {
    try {
      var stored = localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.indexOf(stored) >= 0) return stored;
    } catch (e) { /* ignore */ }
    return DEFAULT_LANG;
  }

  function t(key) {
    var lang = getLang();
    if (DICT[lang] && DICT[lang][key] !== undefined) return DICT[lang][key];
    if (DICT[DEFAULT_LANG] && DICT[DEFAULT_LANG][key] !== undefined) return DICT[DEFAULT_LANG][key];
    return key;
  }

  function applyI18n(root) {
    root = root || document;
    var lang = getLang();
    document.documentElement.lang = (lang === 'zh') ? 'zh-CN' : 'en';

    // 普通文本节点
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    // 含内联 HTML 的节点
    root.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      el.innerHTML = t(el.getAttribute('data-i18n-html'));
    });
    // 属性翻译：data-i18n-attr="placeholder=key1;title=key2"
    root.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
      var spec = el.getAttribute('data-i18n-attr');
      spec.split(';').forEach(function (pair) {
        var parts = pair.split('=');
        if (parts.length !== 2) return;
        var attr = parts[0].trim(), key = parts[1].trim();
        if (attr && key) el.setAttribute(attr, t(key));
      });
    });
    // <title data-i18n="...">
    var titleEl = document.querySelector('title[data-i18n]');
    if (titleEl) document.title = t(titleEl.getAttribute('data-i18n'));

    // 语言切换器的激活状态
    document.querySelectorAll('[data-set-lang]').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-set-lang') === lang);
    });
  }

  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) < 0) return;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* ignore */ }
    applyI18n();
    try {
      document.dispatchEvent(new CustomEvent('langchange', { detail: { lang: lang } }));
    } catch (e) { /* ignore */ }
  }

  function onChange(cb) {
    document.addEventListener('langchange', function (e) { cb(e.detail.lang); });
  }

  function init() {
    applyI18n();
    document.querySelectorAll('[data-set-lang]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.preventDefault();
        setLang(el.getAttribute('data-set-lang'));
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.I18N = {
    t: t,
    setLang: setLang,
    getLang: getLang,
    applyI18n: applyI18n,
    onChange: onChange
  };
})();
