# 03 串口协议、采集与回放

解析器依据海凌科官方《LD6002C 跌倒检测串口协议文档》：

<https://r0.hlktech.com/download/HLK-LD6002C/1/LD6002C%E8%B7%8C%E5%80%92%E6%A3%80%E6%B5%8B%E4%B8%B2%E5%8F%A3%E5%8D%8F%E8%AE%AE%E6%96%87%E6%A1%A3.pdf>

串口参数为 115200、8 数据位、1 停止位、无校验、无硬件流控。

## TinyFrame

```text
SOF(1) | ID(2) | LEN(2) | TYPE(2) | HEAD_CKSUM(1) | DATA(N) | DATA_CKSUM(1)
```

- `SOF` 为 `0x01`。
- `ID`、`LEN`、`TYPE` 为大端序，DATA 多字节字段为小端序。
- 头校验和、数据校验和均为对应字节逐个 XOR 后按位取反。
- 当前解析 `0x0E02` 跌倒状态和 `0x0F09` 人体存在状态。
- 其他校验正确的类型安全跳过，不伪装为 `RadarFrame`。

增量 parser 会保留不完整帧，校验失败时逐字节重新同步，并限制官方最大 DATA 长度 1024。`reset()` 用于切换采样文件时清空 buffer 和旧状态。

## 原始采集

`tools/capture_ld6002c.py` 将 bytes 原样写入 `.bin`，控制台显示 hex，并持续刷新文件。metadata 记录端口、波特率、开始/结束时间、场景、字节数和结束状态。Ctrl+C 或异常退出时，已写入的数据与 metadata 会保留。

## Replay

`ReplayRadarReader` 按可配置 chunk 读取 `.bin` 并送入同一个 parser。原始二进制不包含时间戳，因此 replay 的状态持续时间取决于 `--replay-interval`，不能把它当作原场景精确时间轴。

只有官方协议明确的字段才能加入 parser。扩展距离、点云等字段时，需要对应官方定义与带场景 metadata 的真实采样共同验证。
