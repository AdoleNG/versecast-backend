// public/audio-worklet-processor.js

class VersecastProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
    this._targetSampleRate = 16000;
    this._sourceSampleRate = sampleRate; // from AudioWorklet global
  }

  _downsample(input) {
    if (this._sourceSampleRate === this._targetSampleRate) {
      return input;
    }

    const ratio = this._sourceSampleRate / this._targetSampleRate;
    const newLength = Math.round(input.length / ratio);
    const result = new Float32Array(newLength);

    let offsetResult = 0;
    let offsetBuffer = 0;

    while (offsetResult < newLength) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
      let accum = 0;
      let count = 0;
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < input.length; i++) {
        accum += input[i];
        count++;
      }
      result[offsetResult] = accum / (count || 1);
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }

    return result;
  }

  _floatTo16BitPCM(float32Array) {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);
    let offset = 0;

    for (let i = 0; i < float32Array.length; i++, offset += 2) {
      let s = Math.max(-1, Math.min(1, float32Array[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }

    return buffer;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const channelData = input[0]; // mono
    if (!channelData) return true;

    const downsampled = this._downsample(channelData);
    const pcmBuffer = this._floatTo16BitPCM(downsampled);

    this.port.postMessage(pcmBuffer);

    return true;
  }
}

registerProcessor('versecast-processor', VersecastProcessor);
