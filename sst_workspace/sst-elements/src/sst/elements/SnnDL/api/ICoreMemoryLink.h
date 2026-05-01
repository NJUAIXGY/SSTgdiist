// -*- c++ -*-
//
// ICoreMemoryLink: 平台侧（MultiCorePE）为 core 注入内存 Link 的窄接口。
//
// 目的：
// - MultiCorePE 仅依赖 CoreShellAPI 作为可加载 core API；
// - 内存连接能力作为可选接口通过 dynamic_cast 注入，避免把 setMemoryLink 写进通用 core API。
//

#pragma once

namespace SST { class Link; }

namespace SST { namespace SnnDL {

class ICoreMemoryLink {
public:
    virtual ~ICoreMemoryLink() = default;
    virtual void setMemoryLink(SST::Link* link) = 0;
};

}} // namespace SST::SnnDL

