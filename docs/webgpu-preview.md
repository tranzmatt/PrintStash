# Browser 3D rendering

**Settings → GPU** controls mesh rendering in the current browser. WebGL is
the default. Automatic and WebGPU are experimental choices. WebGPU requires
HTTPS or localhost; ordinary LAN HTTP and browsers without WebGPU use WebGL.

If WebGPU cannot initialize or loses its device, the viewer switches to
compatibility rendering while retaining the camera and loaded model.
Screenshots remain available; a failed capture leaves the viewer usable.
The G-code viewer continues to use WebGL.

To return to the default at any time, choose **Settings → GPU → WebGL
compatibility**. This preference affects the browser only.
[Server preview processing](compute.md) has separate settings and hardware
requirements.
