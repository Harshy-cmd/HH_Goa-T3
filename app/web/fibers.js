/**
 * GhostFibers — WebGL2 Implementation (Based on React Bits Reference)
 *
 * Renders luminous, organic, undulating glowing fibers with volumetric atmosphere.
 * Features:
 * - GPU-accelerated WebGL2 full-screen fragment shader matching React Bits Ghost Fibers.
 * - Slower, calmer wave, rotation, layer, and twist dynamics for a relaxed ambient feel.
 * - Soft luminous fiber core with smooth exponential glow falloff (no razor-wire edges).
 * - Automatic pause when tab is hidden or element is off-screen.
 * - Framerate throttling and DPR clamping to preserve battery & GPU resources.
 * - Live configurable parameters via window.GhostFibers.
 */

(function () {
  'use strict';

  const canvas = document.getElementById('ghostFibersCanvas');
  if (!canvas) return;

  // --- Configuration (tuned for slower, softer, atmospheric visual quality) ---
  const DEFAULTS = {
    lineColor: '#140E35',     // Deep indigo fiber cores
    glowColor: '#3437A0',     // Luminous royal blue/purple atmospheric glow
    speed: 0.07,              // Master animation speed (calm, majestic drift)
    scale: 2.0,               // Zoom level of the fiber field
    rotation: 0.0,            // Static field rotation in degrees
    rotationSpeed: 0.08,      // Slow continuous rotation rate
    layers: 4,                // Number of cumulative fiber layers (1 to 10)
    waveAmplitude: 0.016,     // Strength of recursive wave displacement
    waveFrequency: 3.0,       // Frequency of recursive wave displacement
    waveSpeed: 0.07,          // Slower base speed of layered waves
    layerSpeed: 0.035,        // Subtle parallax wave speed contributed per layer
    twist: 0.1,               // Angular distortion applied per iteration
    twistFrequency: 5.0,      // Radial frequency of angular distortion
    twistSpeed: 0.4,          // Gentle, calm twist animation speed
    lineFrequency: 5.0,       // Base frequency of bright fibers
    lineSpacing: 2.0,         // Frequency increment per layer
    lineSharpness: 6.0,       // Softened core falloff (down from 16 for soft bloom)
    glowFalloff: 6.0,         // Extended glow radius (down from 10 for atmospheric haze)
    glowIntensity: 2.0,       // Luminous bloom multiplier
    brightness: 1.9,          // Final tone mapping exposure
    blueBoost: 1.25,          // Blue channel harmonic boost
    vignette: 0.8,            // Edge darkening strength
    grain: 0.03,              // Fine screen-space film grain
    lightMode: false,         // Dark background mode
    fps: 60,                  // Target render frame rate
    dpr: Math.min(window.devicePixelRatio || 1, 1.5) // Clamped DPR for optimal GPU efficiency
  };

  const config = { ...DEFAULTS };

  const hexToRgb = (hex) => {
    const value = hex.trim().replace(/^#/, '');
    const normalized = value.length === 3
      ? value.split('').map((c) => c + c).join('')
      : value;
    const match = /^([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(normalized);
    if (!match) return [1, 1, 1];
    return [
      parseInt(match[1], 16) / 255,
      parseInt(match[2], 16) / 255,
      parseInt(match[3], 16) / 255,
    ];
  };

  // --- Shaders (React Bits WebGL 2.0 Specification) ---
  const vertexShaderSource = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

  const fragmentShaderSource = `#version 300 es
precision highp float;

uniform vec2 uResolution;
uniform float uTime;
uniform float uSpeed;
uniform float uScale;
uniform float uRotation;
uniform float uLayers;
uniform float uWaveAmplitude;
uniform float uWaveFrequency;
uniform float uWaveSpeed;
uniform float uLayerSpeed;
uniform float uTwist;
uniform float uTwistFrequency;
uniform float uTwistSpeed;
uniform float uLineFrequency;
uniform float uLineSpacing;
uniform float uLineSharpness;
uniform float uGlowFalloff;
uniform float uGlowIntensity;
uniform float uBrightness;
uniform float uBlueBoost;
uniform float uVignette;
uniform float uGrain;
uniform float uRotationSpeed;
uniform float uLightMode;
uniform vec3 uLineColor;
uniform vec3 uGlowColor;

out vec4 fragColor;

#define MAX_LAYERS 10

mat2 rotate2d(float angle) {
  float sine = sin(angle);
  float cosine = cos(angle);
  return mat2(cosine, -sine, sine, cosine);
}

float grainHash(vec2 point) {
  point = floor(point);
  float hash = 52.9829189 * fract(dot(point, vec2(0.065, 0.005)));
  return fract(hash);
}

float layeredGrain(vec2 fragmentPixel) {
  vec2 point = mod(fragmentPixel + vec2(uTime * 30.0, -uTime * 21.0), 1024.0);
  vec2 rotated = mat2(0.8, -0.5, 0.5, 0.8) * point;
  float grain = 0.0;
  grain += 0.40 * grainHash(rotated);
  grain += 0.25 * grainHash(rotated * 2.0 + 17.0);
  grain += 0.20 * grainHash(rotated * 4.0 + 47.0);
  grain += 0.10 * grainHash(rotated * 8.0 + 113.0);
  grain += 0.05 * grainHash(rotated * 16.0 + 191.0);
  return grain;
}

void main() {
  vec2 resolution = max(uResolution, vec2(1.0));
  vec2 uv = (2.0 * gl_FragCoord.xy - resolution) / resolution.y;
  float time = uTime * uSpeed;
  vec3 backdrop = mix(vec3(0.027, 0.027, 0.043), vec3(1.0), step(0.5, uLightMode));
  vec3 centerTone = max(uLineColor * 0.85567 - uGlowColor * 0.06186, vec3(0.0));
  vec3 cloudTone = uLineColor * 0.19588 + uGlowColor * 0.2268;
  vec2 p = uv;
  p /= max(uScale, 0.05);
  p = rotate2d(radians(uRotation) + time * uRotationSpeed) * p;
  vec3 color = vec3(0.0);
  float fiberField = 0.0;

  for (int index = 0; index < MAX_LAYERS; index++) {
    float fi = float(index) + 1.0;
    if (fi > uLayers) break;

    p += uWaveAmplitude * sin(p.yx * fi * uWaveFrequency + time * (uWaveSpeed + fi * uLayerSpeed));

    float radius = length(p);
    float polarAngle = atan(p.y, p.x);
    polarAngle += sin(radius * uTwistFrequency - time * uTwistSpeed + fi) * uTwist;
    p = vec2(cos(polarAngle), sin(polarAngle)) * radius;

    float lines = abs(sin(p.x * (uLineFrequency + fi * uLineSpacing) + sin(p.y * 3.0 + time)));
    lines = pow(max(0.0, 1.0 - lines), uLineSharpness);
    fiberField += lines / fi;
    color += uLineColor * lines / fi;

    float glow = exp(-uGlowFalloff * abs(sin(p.x * 3.0 + time + fi)));
    color += uGlowColor * glow * uGlowIntensity / (fi * 2.0);
  }

  float center = exp(-2.2 * dot(uv, uv));
  color += centerTone * center;

  float cloud = exp(-1.5 * length(uv + vec2(sin(time * 0.3) * 0.25, cos(time * 0.25) * 0.18)));
  color += cloudTone * cloud;

  float vignette = 1.0 - smoothstep(0.35, 1.45, length(uv));
  color *= mix(1.0 - uVignette, 1.0, vignette);
  color = 1.0 - exp(-color * uBrightness);
  color.b *= uBlueBoost;

  vec3 outputColor;
  if (uLightMode > 0.5) {
    float edgeFade = mix(1.0 - uVignette, 1.0, vignette);
    float fibers = pow(smoothstep(0.12, 1.05, fiberField) * edgeFade, 1.5);
    float atmosphere = (center * 0.025 + cloud * 0.015) * edgeFade;
    vec3 fiberInk = mix(backdrop, uLineColor, 0.52);
    vec3 airColor = mix(backdrop, uGlowColor, 0.16);

    outputColor = mix(backdrop, airColor, atmosphere);
    outputColor = mix(outputColor, fiberInk, fibers * 0.3);
  } else {
    outputColor = backdrop + color;
  }

  float noise = (layeredGrain(gl_FragCoord.xy) - 0.5) * uGrain;
  outputColor = clamp(outputColor + noise, 0.0, 1.0);
  fragColor = vec4(outputColor, 1.0);
}
`;

  // --- WebGL2 Context & Compilation ---
  const gl = canvas.getContext('webgl2', {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    powerPreference: 'high-performance'
  });

  if (!gl) {
    console.warn('[GhostFibers] WebGL2 not supported on this browser; background animation disabled.');
    return;
  }

  function compileShader(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const err = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(`Shader compile error: ${err}`);
    }
    return shader;
  }

  let program;
  try {
    const vs = compileShader(gl.VERTEX_SHADER, vertexShaderSource);
    const fs = compileShader(gl.FRAGMENT_SHADER, fragmentShaderSource);
    program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(`Program link error: ${gl.getProgramInfoLog(program)}`);
    }
  } catch (err) {
    console.error('[GhostFibers]', err);
    return;
  }

  // Full-screen triangle buffer
  const positionBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 3, -1, -1, 3]),
    gl.STATIC_DRAW
  );

  const posAttr = gl.getAttribLocation(program, 'position');
  gl.enableVertexAttribArray(posAttr);
  gl.vertexAttribPointer(posAttr, 2, gl.FLOAT, false, 0, 0);

  // Cache uniform locations
  const uniforms = {
    uResolution: gl.getUniformLocation(program, 'uResolution'),
    uTime: gl.getUniformLocation(program, 'uTime'),
    uSpeed: gl.getUniformLocation(program, 'uSpeed'),
    uScale: gl.getUniformLocation(program, 'uScale'),
    uRotation: gl.getUniformLocation(program, 'uRotation'),
    uRotationSpeed: gl.getUniformLocation(program, 'uRotationSpeed'),
    uLayers: gl.getUniformLocation(program, 'uLayers'),
    uWaveAmplitude: gl.getUniformLocation(program, 'uWaveAmplitude'),
    uWaveFrequency: gl.getUniformLocation(program, 'uWaveFrequency'),
    uWaveSpeed: gl.getUniformLocation(program, 'uWaveSpeed'),
    uLayerSpeed: gl.getUniformLocation(program, 'uLayerSpeed'),
    uTwist: gl.getUniformLocation(program, 'uTwist'),
    uTwistFrequency: gl.getUniformLocation(program, 'uTwistFrequency'),
    uTwistSpeed: gl.getUniformLocation(program, 'uTwistSpeed'),
    uLineFrequency: gl.getUniformLocation(program, 'uLineFrequency'),
    uLineSpacing: gl.getUniformLocation(program, 'uLineSpacing'),
    uLineSharpness: gl.getUniformLocation(program, 'uLineSharpness'),
    uGlowFalloff: gl.getUniformLocation(program, 'uGlowFalloff'),
    uGlowIntensity: gl.getUniformLocation(program, 'uGlowIntensity'),
    uBrightness: gl.getUniformLocation(program, 'uBrightness'),
    uBlueBoost: gl.getUniformLocation(program, 'uBlueBoost'),
    uVignette: gl.getUniformLocation(program, 'uVignette'),
    uGrain: gl.getUniformLocation(program, 'uGrain'),
    uLightMode: gl.getUniformLocation(program, 'uLightMode'),
    uLineColor: gl.getUniformLocation(program, 'uLineColor'),
    uGlowColor: gl.getUniformLocation(program, 'uGlowColor'),
  };

  gl.useProgram(program);

  function applyUniforms() {
    gl.useProgram(program);
    gl.uniform1f(uniforms.uSpeed, config.speed);
    gl.uniform1f(uniforms.uScale, config.scale);
    gl.uniform1f(uniforms.uRotation, config.rotation);
    gl.uniform1f(uniforms.uRotationSpeed, config.rotationSpeed);
    gl.uniform1f(uniforms.uLayers, Math.min(Math.max(config.layers, 1), 10));
    gl.uniform1f(uniforms.uWaveAmplitude, config.waveAmplitude);
    gl.uniform1f(uniforms.uWaveFrequency, config.waveFrequency);
    gl.uniform1f(uniforms.uWaveSpeed, config.waveSpeed);
    gl.uniform1f(uniforms.uLayerSpeed, config.layerSpeed);
    gl.uniform1f(uniforms.uTwist, config.twist);
    gl.uniform1f(uniforms.uTwistFrequency, config.twistFrequency);
    gl.uniform1f(uniforms.uTwistSpeed, config.twistSpeed);
    gl.uniform1f(uniforms.uLineFrequency, config.lineFrequency);
    gl.uniform1f(uniforms.uLineSpacing, config.lineSpacing);
    gl.uniform1f(uniforms.uLineSharpness, config.lineSharpness);
    gl.uniform1f(uniforms.uGlowFalloff, config.glowFalloff);
    gl.uniform1f(uniforms.uGlowIntensity, config.glowIntensity);
    gl.uniform1f(uniforms.uBrightness, config.brightness);
    gl.uniform1f(uniforms.uBlueBoost, config.blueBoost);
    gl.uniform1f(uniforms.uVignette, config.vignette);
    gl.uniform1f(uniforms.uGrain, config.grain);
    gl.uniform1f(uniforms.uLightMode, config.lightMode ? 1.0 : 0.0);

    const lColor = hexToRgb(config.lineColor);
    gl.uniform3f(uniforms.uLineColor, lColor[0], lColor[1], lColor[2]);

    const gColor = hexToRgb(config.glowColor);
    gl.uniform3f(uniforms.uGlowColor, gColor[0], gColor[1], gColor[2]);
  }

  applyUniforms();

  // --- Animation State & Loop ---
  let frameId = 0;
  let elapsed = 0;
  let previousTime = performance.now();
  let lastRenderTime = 0;
  let isVisible = true;
  let isPageVisible = !document.hidden;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function render() {
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function resize() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const dpr = config.dpr;

    const renderW = Math.max(1, Math.floor(width * dpr));
    const renderH = Math.max(1, Math.floor(height * dpr));

    if (canvas.width !== renderW || canvas.height !== renderH) {
      canvas.width = renderW;
      canvas.height = renderH;
      gl.viewport(0, 0, renderW, renderH);
      gl.useProgram(program);
      gl.uniform2f(uniforms.uResolution, renderW, renderH);
    }
    render();
  }

  function canAnimate() {
    return isVisible && isPageVisible && !reducedMotion.matches;
  }

  function loop(now) {
    frameId = 0;
    if (!canAnimate()) return;

    const delta = Math.min((now - previousTime) / 1000, 0.1);
    previousTime = now;
    elapsed += delta;

    const frameInterval = 1000 / config.fps - 0.5;
    if (now - lastRenderTime >= frameInterval) {
      gl.useProgram(program);
      gl.uniform1f(uniforms.uTime, elapsed);
      render();
      lastRenderTime = now;
    }

    frameId = requestAnimationFrame(loop);
  }

  function start() {
    if (!canAnimate() || frameId !== 0) return;
    previousTime = performance.now();
    frameId = requestAnimationFrame(loop);
  }

  function stop() {
    if (frameId !== 0) {
      cancelAnimationFrame(frameId);
      frameId = 0;
    }
  }

  // --- Lifecycle & Visibility Listeners ---
  window.addEventListener('resize', resize, { passive: true });

  document.addEventListener('visibilitychange', () => {
    isPageVisible = !document.hidden;
    if (canAnimate()) start();
    else stop();
  });

  reducedMotion.addEventListener('change', () => {
    if (canAnimate()) start();
    else {
      stop();
      render();
    }
  });

  // IntersectionObserver to pause when canvas is completely scrolled out of view
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(
      ([entry]) => {
        isVisible = entry.isIntersecting;
        if (canAnimate()) start();
        else stop();
      },
      { threshold: 0 }
    );
    observer.observe(canvas);
  }

  // Initial setup & start
  resize();
  start();

  // Expose global controller for real-time live parameter inspection & tuning
  window.GhostFibers = {
    config,
    update(newParams = {}) {
      Object.assign(config, newParams);
      applyUniforms();
      resize();
      render();
    },
    reset() {
      Object.assign(config, DEFAULTS);
      applyUniforms();
      resize();
      render();
    }
  };
})();
