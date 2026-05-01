// -*- c++ -*-
//
// IMemoryAccess: 纯地址→字节块的异步读写接口。
// 重要：该接口不得携带 weight/synapse/BCSR/route 等任何语义字段。

#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>

namespace SST { namespace SnnDL {

class IMemoryAccess {
public:
    using RequestId = uint64_t;
    using ReadCallback = std::function<void(RequestId req_id, uint64_t addr, std::vector<uint8_t>&& data)>;
    using WriteCallback = std::function<void(RequestId req_id, uint64_t addr)>;

    virtual ~IMemoryAccess() = default;

    // 异步读：bytes 必须 > 0；失败语义（Phase1-A）：回调 data 为空。
    virtual RequestId read(uint64_t addr, size_t bytes, ReadCallback cb) = 0;

    // 异步写：data.size() 必须 > 0；失败语义：回调可能不会被触发（实现可选择 fail-fast）。
    virtual RequestId write(uint64_t addr, const std::vector<uint8_t>& data, WriteCallback cb) = 0;

    virtual size_t pendingSize() const = 0;
};

}} // namespace SST::SnnDL

