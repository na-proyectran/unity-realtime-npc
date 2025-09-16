using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;

#if TMP_PRESENT
using TMPro;
#endif

/// <summary>
/// Cliente Unity (open-mic opcional) con deltas:
/// - Opcional: usar /events además del socket principal
/// - Enviar: audio (ON por defecto), texto (OFF por defecto)
/// - Recibir: audio (ON), texto (ON)
/// - Valida que al menos una opción esté activa en Enviar y en Recibir
/// - Selector de micrófono y destino de reproducción (AudioSource)
/// - Imagen optimizada: JPEG, máx 1024 px, chunked
/// - Reducción de ruido entrada: high-pass + noise gate (opcional)
/// </summary>
public class RealtimeNPCDeltas : MonoBehaviour
{
    [Header("Servidor")]
    [Tooltip("Base WebSocket, p.ej. wss://<subdominio>.pinggy.link/ws")]
    public string serverUrl = "wss://jwfql-79-116-196-15.a.free.pinggy.link/ws";

    [Tooltip("Conectar también a /events para recibir eventos (opcional).")]
    public bool useEventsSocket = true;

    [Header("Configurar envío")]
    [Tooltip("Enviar audio capturado por micrófono (open-mic).")]
    public bool sendAudio = true; // ON por defecto
    [Tooltip("Enviar mensajes de texto (método SendText).")]
    public bool sendText = false; // OFF por defecto

    [Header("Configurar recepción")]
    [Tooltip("Reproducir deltas de audio recibidos.")]
    public bool receiveAudio = true; // ON por defecto
    [Tooltip("Mostrar deltas de texto recibidos.")]
    public bool receiveText = true;  // ON por defecto

    [Header("Open-mic (captura)")]
    public int captureSampleRate = 24000;
    public bool startOnPlay = true;
    public bool muted = false;

    [Header("Reducción de ruido (entrada)")]
    [Tooltip("Activar filtro pasa-altos + noise gate al audio de entrada.")]
    public bool noiseReduction = false;
    [Tooltip("Corte del filtro pasa-altos (Hz).")]
    public float highpassCutoffHz = 120f;
    [Tooltip("Umbral del noise gate (dBFS). Más alto = más agresivo.")]
    public float gateThresholdDb = -50f;
    [Tooltip("Attack (ms) del gate.")]
    public float gateAttackMs = 15f;
    [Tooltip("Release (ms) del gate.")]
    public float gateReleaseMs = 150f;

    [Header("Salida de audio")]
    public int outputSampleRate = 24000;
    [Tooltip("Fade por chunk (seg) para evitar clics")]
    public float playbackFadeSec = 0.02f;

    [Header("UI (opcional)")]
#if TMP_PRESENT
    public TextMeshProUGUI transcriptTMP;
#endif
    public Text transcriptText;

    [Header("Controles UI (opcional)")]
    public Toggle useEventsToggle;
    public Toggle sendAudioToggle;
    public Toggle sendTextToggle;
    public Toggle receiveAudioToggle;
    public Toggle receiveTextToggle;

    [Header("Selector de micrófono (opcional)")]
#if TMP_PRESENT
    public TMP_Dropdown micDropdown;
#else
    public Dropdown micDropdown;
#endif
    [Tooltip("Nombre del micrófono seleccionado (persistente).")]
    public string selectedMicDevice; // vacío => primero disponible

    [Header("Selector de destino de reproducción (opcional)")]
#if TMP_PRESENT
    public TMP_Dropdown outputDropdown;
#else
    public Dropdown outputDropdown;
#endif
    [Tooltip("Lista de candidatos (se autocompleta en runtime si está vacía).")]
    public List<AudioSource> outputCandidates = new List<AudioSource>();

    [Header("Imagen (optimización)")]
    [Tooltip("Tamaño máximo de imagen (recomendado 1024).")]
    public int maxImageSide = 1024;
    [Range(1, 100)]
    [Tooltip("Calidad JPEG (85 recomendado).")]
    public int jpegQuality = 85;

    // --- Internos ---
    private string sessionId;
    private ClientWebSocket wsMain, wsEvents;
    private CancellationTokenSource cts;

    // Mic
    private string micDevice;
    private AudioClip micClip;
    private int micReadPos;
    private bool capturing;

    // Reducción de ruido (estado)
    private float hp_a0, hp_b1, hp_prevIn, hp_prevOut;
    private float gateEnv = 0f;

    // Transcript
    private readonly ConcurrentQueue<string> uiQueue = new ConcurrentQueue<string>();
    private string currentLine = "";

    // Audio out
    private AudioSource audioSource; // destino actual
    private readonly ConcurrentQueue<short[]> pcmQueue = new ConcurrentQueue<short[]>();
    private float[] residual; private int residualPos;

    // Imagen (chunking)
    private const int IMAGE_CHUNK = 60_000;

    // ===== Ciclo de vida =====
    private void Awake()
    {
        // AudioSource por defecto (propio)
        audioSource = GetComponent<AudioSource>() ?? gameObject.AddComponent<AudioSource>();
        PrepareAudioSource(audioSource);

        // UI wiring
        WireOptionalToggles();
        ValidateOptions(enforce: true);

        // Poblar dropdowns si están asignados
        RefreshMicListUI();
        RefreshOutputTargetsUI();
    }

    private async void Start()
    {
        await Connect();
        if (startOnPlay && sendAudio) StartOpenMic();
    }

    private async void OnDestroy() => await Shutdown();

    private void OnValidate()
    {
        ValidateOptions(enforce: true);
        WireOptionalToggles();
        UpdateToggleStatesFromFlags();
    }

    // ===== Util: preparar un AudioSource como destino de voz
    private void PrepareAudioSource(AudioSource src)
    {
        if (src == null) return;
        src.loop = true;
        if (src.clip == null || src.clip.frequency != outputSampleRate)
            src.clip = AudioClip.Create("NPC_Out", outputSampleRate * 10, 1, outputSampleRate, true, OnAudioRead, _ => { });
        src.spatialBlend = 0f; // voz 2D; cámbialo a 1.0 si quieres posicionarla 3D
        if (!src.isPlaying) src.Play();
    }

    // ===== UI toggles opcionales =====
    private void WireOptionalToggles()
    {
        if (useEventsToggle != null)
        {
            useEventsToggle.onValueChanged.RemoveAllListeners();
            useEventsToggle.isOn = useEventsSocket;
            useEventsToggle.onValueChanged.AddListener(v => useEventsSocket = v);
        }
        if (sendAudioToggle != null)
        {
            sendAudioToggle.onValueChanged.RemoveAllListeners();
            sendAudioToggle.isOn = sendAudio;
            sendAudioToggle.onValueChanged.AddListener(v =>
            {
                sendAudio = v;
                ValidateOptions(enforce: true);
                if (sendAudio && !capturing && startOnPlay) StartOpenMic();
                if (!sendAudio && capturing) StopOpenMic();
            });
        }
        if (sendTextToggle != null)
        {
            sendTextToggle.onValueChanged.RemoveAllListeners();
            sendTextToggle.isOn = sendText;
            sendTextToggle.onValueChanged.AddListener(v =>
            {
                sendText = v;
                ValidateOptions(enforce: true);
            });
        }
        if (receiveAudioToggle != null)
        {
            receiveAudioToggle.onValueChanged.RemoveAllListeners();
            receiveAudioToggle.isOn = receiveAudio;
            receiveAudioToggle.onValueChanged.AddListener(v =>
            {
                receiveAudio = v;
                ValidateOptions(enforce: true);
                if (!receiveAudio) { pcmQueue.Clear(); residual = null; residualPos = 0; }
            });
        }
        if (receiveTextToggle != null)
        {
            receiveTextToggle.onValueChanged.RemoveAllListeners();
            receiveTextToggle.isOn = receiveText;
            receiveTextToggle.onValueChanged.AddListener(v =>
            {
                receiveText = v;
                ValidateOptions(enforce: true);
            });
        }

        // Mic dropdown
        if (micDropdown != null)
        {
#if TMP_PRESENT
            micDropdown.onValueChanged.RemoveAllListeners();
            micDropdown.onValueChanged.AddListener(SetMicByDropdownIndex);
#else
            micDropdown.onValueChanged.RemoveAllListeners();
            micDropdown.onValueChanged.AddListener(SetMicByDropdownIndex);
#endif
        }

        // Output dropdown
        if (outputDropdown != null)
        {
#if TMP_PRESENT
            outputDropdown.onValueChanged.RemoveAllListeners();
            outputDropdown.onValueChanged.AddListener(SetOutputByDropdownIndex);
#else
            outputDropdown.onValueChanged.RemoveAllListeners();
            outputDropdown.onValueChanged.AddListener(SetOutputByDropdownIndex);
#endif
        }
    }

    private void UpdateToggleStatesFromFlags()
    {
        if (useEventsToggle) useEventsToggle.isOn = useEventsSocket;
        if (sendAudioToggle) sendAudioToggle.isOn = sendAudio;
        if (sendTextToggle) sendTextToggle.isOn = sendText;
        if (receiveAudioToggle) receiveAudioToggle.isOn = receiveAudio;
        if (receiveTextToggle) receiveTextToggle.isOn = receiveText;
    }

    private void ValidateOptions(bool enforce)
    {
        // Siempre al menos una de Enviar
        if (!sendAudio && !sendText)
        {
            if (enforce)
            {
                Debug.LogWarning("[RealtimeNPC] Debe haber al menos una opción activa en 'Enviar'. Activando 'Enviar audio'.");
                sendAudio = true;
                if (sendAudioToggle) sendAudioToggle.isOn = true;
            }
        }
        // Siempre al menos una de Recibir
        if (!receiveAudio && !receiveText)
        {
            if (enforce)
            {
                Debug.LogWarning("[RealtimeNPC] Debe haber al menos una opción activa en 'Recibir'. Activando 'Recibir texto'.");
                receiveText = true;
                if (receiveTextToggle) receiveTextToggle.isOn = true;
            }
        }
    }

    // ===== Mic selector =====
    public void RefreshMicListUI()
    {
        var devices = Microphone.devices;
        // Guardar el índice del seleccionado actual (si existe)
        int currentIdx = Mathf.Max(0, Array.IndexOf(devices, string.IsNullOrEmpty(selectedMicDevice) ? devices.Length > 0 ? devices[0] : null : selectedMicDevice));

        if (micDropdown != null)
        {
#if TMP_PRESENT
            micDropdown.ClearOptions();
            var opts = new List<string>(devices);
            if (opts.Count == 0) opts.Add("(sin micrófonos)");
            micDropdown.AddOptions(opts);
            micDropdown.value = Mathf.Clamp(currentIdx, 0, Mathf.Max(0, opts.Count - 1));
            micDropdown.RefreshShownValue();
#else
            micDropdown.ClearOptions();
            var opts = new List<string>(devices);
            if (opts.Count == 0) opts.Add("(sin micrófonos)");
            micDropdown.AddOptions(opts);
            micDropdown.value = Mathf.Clamp(currentIdx, 0, Mathf.Max(0, opts.Count - 1));
#endif
        }

        // Asegurar valor
        if (devices.Length > 0)
        {
            if (string.IsNullOrEmpty(selectedMicDevice) || Array.IndexOf(devices, selectedMicDevice) < 0)
                selectedMicDevice = devices[currentIdx];
        }
        else
        {
            selectedMicDevice = null;
        }
    }

    private void SetMicByDropdownIndex(int idx)
    {
        var devices = Microphone.devices;
        if (devices.Length == 0) { selectedMicDevice = null; return; }
        idx = Mathf.Clamp(idx, 0, devices.Length - 1);
        var newDev = devices[idx];
        if (newDev == selectedMicDevice) return;

        selectedMicDevice = newDev;
        Debug.Log($"[RealtimeNPC] Mic seleccionado: {selectedMicDevice}");

        // Si estamos capturando, reiniciar con el nuevo
        if (capturing)
        {
            StopOpenMic();
            if (sendAudio) StartOpenMic();
        }
    }

    // ===== Output selector =====
    public void RefreshOutputTargetsUI()
    {
        // Autocompletar candidatos si la lista está vacía
        if (outputCandidates == null || outputCandidates.Count == 0)
        {
            outputCandidates = new List<AudioSource>(FindObjectsOfType<AudioSource>());
            // Asegura que el propio esté primero
            if (!outputCandidates.Contains(audioSource))
                outputCandidates.Insert(0, audioSource);
        }

        if (outputDropdown != null)
        {
            var labels = new List<string>();
            foreach (var a in outputCandidates)
                labels.Add(a != null ? a.gameObject.name + " : " + a.GetType().Name : "(null)");

#if TMP_PRESENT
            outputDropdown.ClearOptions();
            if (labels.Count == 0) labels.Add("(sin AudioSources)");
            outputDropdown.AddOptions(labels);
            outputDropdown.value = 0;
            outputDropdown.RefreshShownValue();
#else
            outputDropdown.ClearOptions();
            if (labels.Count == 0) labels.Add("(sin AudioSources)");
            outputDropdown.AddOptions(labels);
            outputDropdown.value = 0;
#endif
        }
    }

    private void SetOutputByDropdownIndex(int idx)
    {
        if (outputCandidates == null || outputCandidates.Count == 0) return;
        idx = Mathf.Clamp(idx, 0, outputCandidates.Count - 1);
        var target = outputCandidates[idx];
        if (target == null) return;

        audioSource = target;
        PrepareAudioSource(audioSource);
        Debug.Log($"[RealtimeNPC] Salida de audio -> {audioSource.gameObject.name}");
    }

    // ===== Conexión =====
    public async Task Connect()
    {
        ValidateOptions(enforce: true);

        sessionId = "session_" + Guid.NewGuid().ToString("N").Substring(0, 8);
        cts = new CancellationTokenSource();

        wsMain = new ClientWebSocket();
        await wsMain.ConnectAsync(new Uri($"{serverUrl}/{sessionId}"), cts.Token);
        _ = ReceiveLoop(wsMain, "main");

        if (useEventsSocket)
        {
            try
            {
                wsEvents = new ClientWebSocket();
                await wsEvents.ConnectAsync(new Uri($"{serverUrl}/{sessionId}/events"), cts.Token);
                _ = ReceiveLoop(wsEvents, "events");
            }
            catch (Exception ex)
            {
                Debug.Log($"[RealtimeNPC] /events no disponible: {ex.Message}. Continuando solo con el socket principal.");
                wsEvents?.Dispose(); wsEvents = null;
            }
        }
    }

    private async Task Shutdown()
    {
        StopOpenMic();
        try {
            if (wsMain != null && wsMain.State == WebSocketState.Open)
                await wsMain.CloseAsync(WebSocketCloseStatus.NormalClosure, "closing", cts.Token);
            if (wsEvents != null && wsEvents.State == WebSocketState.Open)
                await wsEvents.CloseAsync(WebSocketCloseStatus.NormalClosure, "closing", cts.Token);
        } catch { }
        wsMain?.Dispose(); wsEvents?.Dispose(); cts?.Dispose();
    }

    private async Task ReceiveLoop(ClientWebSocket ws, string tag)
    {
        var buf = new byte[64 * 1024];
        try
        {
            while (ws.State == WebSocketState.Open)
            {
                var sb = new StringBuilder();
                WebSocketReceiveResult r;
                do {
                    r = await ws.ReceiveAsync(new ArraySegment<byte>(buf), cts.Token);
                    if (r.MessageType == WebSocketMessageType.Close) {
                        await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "", cts.Token);
                        return;
                    }
                    if (r.MessageType == WebSocketMessageType.Text)
                        sb.Append(Encoding.UTF8.GetString(buf, 0, r.Count));
                } while (!r.EndOfMessage);

                HandleEvent(sb.ToString());
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex) { Debug.LogWarning($"[RX {tag}] {ex.Message}"); }
    }

    // ===== Open-mic =====
    public void SetMuted(bool m) => muted = m;

    public void StartOpenMic()
    {
        if (!sendAudio)
        {
            Debug.Log("[RealtimeNPC] 'Enviar audio' está desactivado. No se iniciará la captura.");
            return;
        }

        if (capturing) return;

        var devices = Microphone.devices;
        if (devices.Length == 0) { Debug.LogWarning("No hay micrófono."); return; }

        // Determina el dispositivo a usar
        if (!string.IsNullOrEmpty(selectedMicDevice) && Array.IndexOf(devices, selectedMicDevice) >= 0)
            micDevice = selectedMicDevice;
        else
            micDevice = devices[0];

        micClip = Microphone.Start(micDevice, true, 10, captureSampleRate);
        micReadPos = 0; capturing = true;

        // Inicializa filtros del NR si procede
        RecomputeHighpassCoeffs();

        StartCoroutine(CapLoop());
        Debug.Log($"[RealtimeNPC] Capturando de '{micDevice}' @ {captureSampleRate} Hz");
    }

    public void StopOpenMic()
    {
        if (!capturing) return;
        capturing = false;
        if (!string.IsNullOrEmpty(micDevice) && Microphone.IsRecording(micDevice)) Microphone.End(micDevice);
        micClip = null;
        hp_prevIn = hp_prevOut = 0f;
        gateEnv = 0f;
    }

    private System.Collections.IEnumerator CapLoop()
    {
        var wait = new WaitForSeconds(0.03f);
        float[] f = new float[4096];

        while (capturing)
        {
            yield return wait;

            if (wsMain == null || wsMain.State != WebSocketState.Open || micClip == null) continue;
            if (!sendAudio) continue;

            int micPos = Microphone.GetPosition(micDevice);
            int avail = micPos - micReadPos; if (avail < 0) avail += micClip.samples;
            int toRead = Mathf.Min(avail, f.Length);

            while (toRead > 0)
            {
                micClip.GetData(f, micReadPos);
                micReadPos = (micReadPos + toRead) % micClip.samples;

                if (!muted)
                {
                    if (noiseReduction) ProcessNoiseReduction(f, toRead);

                    short[] s = new short[toRead];
                    for (int i = 0; i < toRead; i++)
                        s[i] = (short)Mathf.RoundToInt(Mathf.Clamp(f[i], -1f, 1f) * 32767f);
                    SendAudio(s);
                }

                micPos = Microphone.GetPosition(micDevice);
                avail = micPos - micReadPos; if (avail < 0) avail += micClip.samples;
                toRead = Mathf.Min(avail, f.Length);
            }
        }
    }

    // ===== Reducción de ruido sencilla =====
    private void RecomputeHighpassCoeffs()
    {
        float sr = Mathf.Max(8000, captureSampleRate);
        float fc = Mathf.Clamp(highpassCutoffHz, 20f, sr * 0.45f);
        float x = Mathf.Exp(-2f * Mathf.PI * fc / sr);
        hp_b1 = x;
        hp_a0 = (1f + x) * 0.5f;
    }

    private void ProcessNoiseReduction(float[] buf, int count)
    {
        if (count <= 0) return;
        // 1) High-pass
        for (int i = 0; i < count; i++)
        {
            float inSample = buf[i];
            float y = hp_a0 * (inSample - hp_prevIn) + hp_b1 * hp_prevOut;
            hp_prevIn = inSample;
            hp_prevOut = y;
            buf[i] = y;
        }

        // 2) Noise gate (envelope con attack/release)
        float sr = Mathf.Max(8000f, captureSampleRate);
        float att = Mathf.Clamp(gateAttackMs / 1000f, 0.001f, 0.2f);
        float rel = Mathf.Clamp(gateReleaseMs / 1000f, 0.02f, 0.5f);
        float attCoeff = Mathf.Exp(-1f / (att * sr));
        float relCoeff = Mathf.Exp(-1f / (rel * sr));
        float thrLin = Mathf.Pow(10f, gateThresholdDb / 20f);

        for (int i = 0; i < count; i++)
        {
            float x = Mathf.Abs(buf[i]);
            if (x > gateEnv) gateEnv = attCoeff * gateEnv + (1f - attCoeff) * x;
            else             gateEnv = relCoeff * gateEnv + (1f - relCoeff) * x;

            float g = gateEnv >= thrLin ? 1f : 0f; // puerta dura
            buf[i] *= g;
        }
    }

    // ===== Envío =====
    public async void SendAudio(short[] samples)
    {
        if (!sendAudio) return;
        if (wsMain == null || wsMain.State != WebSocketState.Open) return;
        var sb = new StringBuilder();
        sb.Append("{\"type\":\"audio\",\"data\":[");
        for (int i = 0; i < samples.Length; i++) { if (i > 0) sb.Append(','); sb.Append(samples[i]); }
        sb.Append("]}");
        await Raw(wsMain, sb.ToString());
    }

    public async void SendText(string text)
    {
        if (!sendText)
        {
            Debug.LogWarning("[RealtimeNPC] 'Enviar texto' está desactivado.");
            return;
        }
        if (wsMain == null || wsMain.State != WebSocketState.Open) return;
        await Raw(wsMain, "{\"type\":\"interrupt\"}");
        await Raw(wsMain, "{\"type\":\"text\",\"text\":\"" + Escape(text) + "\"}");
    }

    public async void CommitAudio()
    {
        if (wsMain == null || wsMain.State != WebSocketState.Open) return;
        await Raw(wsMain, "{\"type\":\"commit_audio\"}");
    }

    /// <summary>
    /// Envía una Texture2D como DataURL JPEG optimizado:
    /// - RGB24
    /// - Escala down si lado mayor > maxImageSide
    /// - JPEG quality configurable
    /// - Chunked
    /// </summary>
    public async void SendImage(Texture2D source, string promptText = "")
    {
        if (wsMain == null || wsMain.State != WebSocketState.Open || source == null) return;

        await Raw(wsMain, "{\"type\":\"interrupt\"}");

        Texture2D resized = EnsureOptimizedImage(source, maxImageSide);
        byte[] jpg = resized.EncodeToJPG(Mathf.Clamp(jpegQuality, 1, 100));
        string b64 = Convert.ToBase64String(jpg);
        string dataUrl = "data:image/jpeg;base64," + b64;

        string id = "img_" + Guid.NewGuid().ToString("N").Substring(0, 6);
        string start = $"{{\"type\":\"image_start\",\"id\":\"{id}\",\"text\":\"{Escape(promptText)}\"}}";
        await Raw(wsMain, start);

        for (int i = 0; i < dataUrl.Length; i += IMAGE_CHUNK)
        {
            string chunk = dataUrl.Substring(i, Math.Min(IMAGE_CHUNK, dataUrl.Length - i));
            string msg = $"{{\"type\":\"image_chunk\",\"id\":\"{id}\",\"chunk\":\"{Escape(chunk)}\"}}";
            await Raw(wsMain, msg);
        }

        string endMsg = $"{{\"type\":\"image_end\",\"id\":\"{id}\"}}";
        await Raw(wsMain, endMsg);

        if (resized != source) Destroy(resized);
    }

    private Texture2D EnsureOptimizedImage(Texture2D src, int maxSide)
    {
        int w = src.width, h = src.height;
        float scale = 1f;
        int maxDim = Mathf.Max(w, h);
        if (maxDim > maxSide) scale = (float)maxSide / maxDim;

        int newW = Mathf.Max(1, Mathf.RoundToInt(w * scale));
        int newH = Mathf.Max(1, Mathf.RoundToInt(h * scale));

        if (Mathf.Abs(scale - 1f) < 0.0001f && src.format == TextureFormat.RGB24)
            return src;

        var rt = RenderTexture.GetTemporary(newW, newH, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
        var prev = RenderTexture.active;
        Graphics.Blit(src, rt);
        RenderTexture.active = rt;

        var tex = new Texture2D(newW, newH, TextureFormat.RGB24, false, false);
        tex.ReadPixels(new Rect(0, 0, newW, newH), 0, 0, false);
        tex.Apply(false, false);

        RenderTexture.active = prev;
        RenderTexture.ReleaseTemporary(rt);
        return tex;
    }

    // ===== Utilidades envío =====
    private static Task Raw(ClientWebSocket s, string p)
      => s.SendAsync(new ArraySegment<byte>(Encoding.UTF8.GetBytes(p)), WebSocketMessageType.Text, true, CancellationToken.None);

    private static string Escape(string s) => string.IsNullOrEmpty(s) ? "" : s.Replace("\\","\\\\").Replace("\"","\\\"").Replace("\n","\\n").Replace("\r","\\r");

    // ===== Deltas (recepción) =====
    private void HandleEvent(string json)
    {
        // Nuevo turno
        if (json.Contains("\"type\":\"response.started\""))
        {
            if (receiveAudio) { pcmQueue.Clear(); residual = null; residualPos = 0; }
            EnqueueUIRefresh();
        }

        // Texto delta
        if (receiveText && json.Contains("\"type\":\"response.output_text.delta\"") && TryExtractText(json, out var delta))
        {
            uiQueue.Enqueue(delta);
        }

        // Audio delta (PCM16 LE base64)
        if (receiveAudio && (json.Contains("\"type\":\"response.audio.delta\"") || json.Contains("\"type\":\"audio\"")) &&
            TryExtractBase64(json, out var b64))
        {
            var bytes = SafeFromBase64(b64);
            if (bytes != null && bytes.Length >= 2 && bytes.Length % 2 == 0)
            {
                var pcm = new short[bytes.Length / 2];
                Buffer.BlockCopy(bytes, 0, pcm, 0, bytes.Length);
                ApplyFadeInOut(pcm, playbackFadeSec, outputSampleRate);
                pcmQueue.Enqueue(pcm);
            }
        }

        // Sugerencia de commit por timeout del VAD
        if (json.Contains("\"type\":\"input_audio_timeout_triggered\""))
            CommitAudio();

        // Fin de respuesta
        if (receiveText && json.Contains("\"type\":\"response.completed\""))
            uiQueue.Enqueue("\n");
    }

    private void EnqueueUIRefresh()
    {
#if TMP_PRESENT
        if (transcriptTMP) transcriptTMP.text = currentLine;
#endif
        if (transcriptText) transcriptText.text = currentLine;
    }

    private static bool TryExtractText(string json, out string text)
    {
        text = null;
        int i = json.IndexOf("\"text\":\"", StringComparison.Ordinal);
        if (i < 0) return false;
        int p = i + 8;
        var sb = new StringBuilder();
        for (; p < json.Length; p++)
        {
            char c = json[p];
            if (c == '\"') { text = sb.ToString(); return !string.IsNullOrEmpty(text); }
            if (c == '\\' && p + 1 < json.Length)
            {
                char n = json[p + 1];
                if (n == 'n'){ sb.Append('\n'); p++; continue; }
                if (n == 'r'){ sb.Append('\r'); p++; continue; }
                if (n == 't'){ sb.Append('\t'); p++; continue; }
                if (n == '\\' || n == '\"' || n == '/') { sb.Append(n); p++; continue; }
            }
            else sb.Append(c);
        }
        return false;
    }

    private static bool TryExtractBase64(string json, out string b64)
    {
        b64 = ExtractStringField(json, "audio");
        if (string.IsNullOrEmpty(b64)) b64 = ExtractStringField(json, "data");
        return !string.IsNullOrEmpty(b64) && b64.Length > 8;
    }

    private static string ExtractStringField(string json, string field)
    {
        string key = $"\"{field}\":\"";
        int i = json.IndexOf(key, StringComparison.Ordinal);
        if (i < 0) return null;
        int p = i + key.Length;
        var sb = new StringBuilder();
        for (; p < json.Length; p++)
        {
            char c = json[p];
            if (c == '\"') return sb.ToString();
            if (c == '\\' && p + 1 < json.Length)
            {
                char n = json[p + 1];
                if (n == 'n'){ sb.Append('\n'); p++; continue; }
                if (n == 'r'){ sb.Append('\r'); p++; continue; }
                if (n == 't'){ sb.Append('\t'); p++; continue; }
                if (n == '\\' || n == '\"' || n == '/') { sb.Append(n); p++; continue; }
            }
            else sb.Append(c);
        }
        return null;
    }

    private static byte[] SafeFromBase64(string s) { try { return Convert.FromBase64String(s); } catch { return null; } }

    // ===== Audio out (pull) =====
    private void OnAudioRead(float[] data)
    {
        int i = 0;

        // residual primero
        if (residual != null)
        {
            while (i < data.Length && residualPos < residual.Length)
                data[i++] = residual[residualPos++];
            if (residualPos >= residual.Length) { residual = null; residualPos = 0; }
        }

        // cola
        while (i < data.Length)
        {
            if (!pcmQueue.TryDequeue(out var pcm))
            {
                while (i < data.Length) data[i++] = 0f;
                return;
            }
            float inv = 1f / 32768f;
            int n = pcm.Length;
            int copy = Mathf.Min(n, data.Length - i);

            for (int k = 0; k < copy; k++) data[i + k] = Mathf.Clamp(pcm[k] * inv, -1f, 1f);
            i += copy;

            if (copy < n)
            {
                int rest = n - copy;
                residual = new float[rest];
                for (int k = 0; k < rest; k++) residual[k] = Mathf.Clamp(pcm[copy + k] * inv, -1f, 1f);
                residualPos = 0;
            }
        }
    }

    private void ApplyFadeInOut(short[] pcm, float fadeSec, int sr)
    {
        if (!receiveAudio) return;
        if (fadeSec <= 0f || pcm.Length < 8) return;
        int f = Mathf.Clamp(Mathf.RoundToInt(fadeSec * sr), 8, Mathf.Min(2000, pcm.Length / 4));
        for (int i = 0; i < f; i++)
        {
            float g = (i + 1) / (float)f;
            pcm[i] = (short)Mathf.RoundToInt(pcm[i] * g);
            int j = pcm.Length - 1 - i;
            pcm[j] = (short)Mathf.RoundToInt(pcm[j] * (1f - g));
        }
    }

    // ===== UI =====
    private void Update()
    {
        while (uiQueue.TryDequeue(out var d))
        {
            if (!receiveText) continue;
            currentLine += d;
#if TMP_PRESENT
            if (transcriptTMP) transcriptTMP.text = currentLine;
#endif
            if (transcriptText) transcriptText.text = currentLine;
        }
    }
}
