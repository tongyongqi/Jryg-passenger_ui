import Foundation
import Vision
import ImageIO

struct TextObservation: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

func recognize() throws {
    guard CommandLine.arguments.count == 3,
          let maxY = Double(CommandLine.arguments[2]), maxY > 0, maxY <= 1 else {
        throw NSError(domain: "RouteOCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Expected screenshot path and map bottom fraction"])
    }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hant", "zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    request.regionOfInterest = CGRect(x: 0, y: 1 - maxY, width: 1, height: maxY)
    let handler = VNImageRequestHandler(url: url, options: [:])
    try handler.perform([request])
    let observations = (request.results ?? []).compactMap { observation -> TextObservation? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return TextObservation(text: candidate.string, confidence: candidate.confidence,
                               x: box.minX, y: 1 - box.maxY, width: box.width, height: box.height)
    }
    let data = try JSONEncoder().encode(observations)
    FileHandle.standardOutput.write(data)
}

do {
    try recognize()
} catch {
    FileHandle.standardError.write(Data("Vision OCR failed: \(error.localizedDescription)\n".utf8))
    exit(1)
}
