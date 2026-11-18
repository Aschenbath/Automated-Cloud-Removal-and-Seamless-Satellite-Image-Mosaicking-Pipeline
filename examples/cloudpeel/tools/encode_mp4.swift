// Encode the frames listed in <frames-dir>/frames.txt as an H.264 MP4 (30 fps),
// using macOS's own AVFoundation, so no ffmpeg is needed.
//
//   swift tools/encode_mp4.swift <frames-dir> <out.mp4>
import AVFoundation
import AppKit

let args = CommandLine.arguments
guard args.count == 3 else { print("usage: encode_mp4.swift <frames-dir> <out.mp4>"); exit(1) }
let dir = URL(fileURLWithPath: args[1])
let out = URL(fileURLWithPath: args[2])
let names = try String(contentsOf: dir.appendingPathComponent("frames.txt"), encoding: .utf8)
    .split(separator: "\n").map(String.init)

func cgImage(_ name: String) -> CGImage {
    let img = NSImage(contentsOf: dir.appendingPathComponent(name))!
    var rect = CGRect(origin: .zero, size: img.size)
    return img.cgImage(forProposedRect: &rect, context: nil, hints: nil)!
}

let firstImage = cgImage(names[0])
let width = firstImage.width, height = firstImage.height
try? FileManager.default.removeItem(at: out)
let writer = try AVAssetWriter(outputURL: out, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width, AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 6_000_000,
                                      AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel],
])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height,
])
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

var cache: (String, CVPixelBuffer)? = nil
for (i, name) in names.enumerated() {
    while !input.isReadyForMoreMediaData { usleep(2000) }
    let buffer: CVPixelBuffer
    if let c = cache, c.0 == name { buffer = c.1 } else {
        var pb: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pb)
        buffer = pb!
        CVPixelBufferLockBaseAddress(buffer, [])
        let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buffer), width: width, height: height,
                            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                            space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
        ctx.draw(cgImage(name), in: CGRect(x: 0, y: 0, width: width, height: height))
        CVPixelBufferUnlockBaseAddress(buffer, [])
        cache = (name, buffer)
    }
    adaptor.append(buffer, withPresentationTime: CMTime(value: CMTimeValue(i), timescale: 30))
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
print(writer.status == .completed ? "wrote \(out.path) (\(names.count) frames, \(width)x\(height))"
                                  : "failed: \(String(describing: writer.error))")
