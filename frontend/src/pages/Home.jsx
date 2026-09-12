import { useEffect, useRef, useState } from 'react';
import api from '../api';
import { BuiltInMaterialCanvas } from '../components/BuiltInMaterialCanvas';
import { builtInCharacters, builtInScenes } from '../components/builtInMaterialOptions';
import '../styles/Home.css';

const fallbackVoices = [
  { id: 'zh-TW-HsiaoChenNeural', name: '曉臻（台灣女聲）' },
  { id: 'zh-TW-YunJheNeural', name: '雲哲（台灣男聲）' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '曉曉（中文女聲）' },
  { id: 'zh-CN-YunxiNeural', name: '雲希（中文男聲）' },
  { id: 'en-US-JennyNeural', name: 'Jenny（英文女聲）' },
  { id: 'en-US-GuyNeural', name: 'Guy（英文男聲）' },
];

const createEmptySegment = (builtinCharacter = '', builtinScene = '') => ({
  text: '',
  status: 'idle',
  audioUrl: '',
  duration: 0,
  size: 0,
  materialSource: 'builtin',
  keyword: '',
  builtinCharacter,
  builtinScene,
  builtinCompositeKey: '',
  materialStatus: 'idle',
  material: null,
  materialIds: [],
  showMaterial: false,
  error: '',
  materialError: '',
});

const getBuiltinCompositeKey = (segment, videoFormat) =>
  `${segment.builtinCharacter}|${segment.builtinScene}|${videoFormat}`;

const canSaveBuiltinMaterial = (segment, videoFormat) =>
  Boolean(
    segment.audioUrl &&
    segment.builtinCharacter &&
    segment.builtinScene &&
    segment.builtinCompositeKey === getBuiltinCompositeKey(segment, videoFormat),
  );

const formatDuration = (seconds) => {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00';

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${remainingSeconds}`;
};

const formatFileSize = (bytes) => {
  if (!bytes) return '0 KB';

  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const getTrimmedVideoUrl = (videoUrl, trimEnd) => `${videoUrl}#t=0,${trimEnd}`;

const videoFormats = [
  { id: 'short', name: '短影片' },
  { id: 'long', name: '長影片' },
];

function Home() {
  const [voice, setVoice] = useState(fallbackVoices[0].id);
  const [videoFormat, setVideoFormat] = useState('short');
  const [voices, setVoices] = useState(fallbackVoices);
  const [extraSegmentCount, setExtraSegmentCount] = useState(1);
  const [segmentCount, setSegmentCount] = useState(1);
  const [segments, setSegments] = useState([createEmptySegment()]);
  const [composeStatus, setComposeStatus] = useState('idle');
  const [composeError, setComposeError] = useState('');
  const [resultVideoUrl, setResultVideoUrl] = useState('');
  const [workflowStep, setWorkflowStep] = useState(1);
  const [selectedBuiltinCharacter, setSelectedBuiltinCharacter] = useState('');
  const [selectedBuiltinScene, setSelectedBuiltinScene] = useState('');
  const segmentsRef = useRef(segments);
  const resultVideoUrlRef = useRef(resultVideoUrl);
  const talkingCompositeRef = useRef(null);
  const builtinCanvasRefs = useRef({});
  const builtinMaterialRequestRefs = useRef({});

  useEffect(() => {
    api
      .get('/api/tts/voices/')
      .then((res) => {
        if (Array.isArray(res.data) && res.data.length > 0) {
          setVoices(res.data);
          setVoice(res.data[0].id);
        }
      })
      .catch(() => {
        setVoices(fallbackVoices);
      });
  }, []);

  useEffect(() => {
    setSegments((currentSegments) => {
      const nextSegments = currentSegments.slice(0, segmentCount);

      while (nextSegments.length < segmentCount) {
        nextSegments.push(createEmptySegment(selectedBuiltinCharacter, selectedBuiltinScene));
      }

      currentSegments.slice(segmentCount).forEach((segment) => {
        if (segment.audioUrl) URL.revokeObjectURL(segment.audioUrl);
      });

      return nextSegments;
    });
  }, [segmentCount, selectedBuiltinCharacter, selectedBuiltinScene]);

  useEffect(() => {
    segmentsRef.current = segments;
  }, [segments]);

  useEffect(() => {
    resultVideoUrlRef.current = resultVideoUrl;
  }, [resultVideoUrl]);

  useEffect(() => {
    return () => {
      segmentsRef.current.forEach((segment) => {
        if (segment.audioUrl) URL.revokeObjectURL(segment.audioUrl);
      });

      if (resultVideoUrlRef.current) {
        URL.revokeObjectURL(resultVideoUrlRef.current);
      }
    };
  }, []);

  const resetResultVideo = () => {
    if (resultVideoUrlRef.current) {
      URL.revokeObjectURL(resultVideoUrlRef.current);
    }

    setResultVideoUrl('');
    setComposeStatus('idle');
    setComposeError('');
  };

  const updateSegmentText = (index, text) => {
    resetResultVideo();
    setSegments((currentSegments) =>
      currentSegments.map((segment, segmentIndex) => {
        if (segmentIndex !== index) return segment;
        if (segment.audioUrl) URL.revokeObjectURL(segment.audioUrl);

        return {
          ...segment,
          text,
          status: 'idle',
          audioUrl: '',
          duration: 0,
          size: 0,
          materialStatus: 'idle',
          material: null,
          materialIds: [],
          showMaterial: false,
          error: '',
          materialError: '',
        };
      }),
    );
  };

  const updateSegmentKeyword = (index, keyword) => {
    resetResultVideo();
    setSegments((currentSegments) =>
      currentSegments.map((segment, segmentIndex) =>
        segmentIndex === index
          ? {
              ...segment,
              keyword,
              materialStatus: 'idle',
              material: null,
              materialIds: [],
              showMaterial: false,
              materialError: '',
            }
          : segment,
      ),
    );
  };

  const recordCanvasClip = (canvas, duration = 1.2) =>
    new Promise((resolve, reject) => {
      if (!canvas?.captureStream || !window.MediaRecorder) {
        reject(new Error('此瀏覽器不支援 Canvas 素材錄製。'));
        return;
      }

      const stream = canvas.captureStream(30);
      const mimeType = [
        'video/mp4;codecs=avc1.42E01E',
        'video/mp4',
        'video/webm;codecs=vp9',
        'video/webm;codecs=vp8',
        'video/webm',
      ].find((type) => MediaRecorder.isTypeSupported(type));
      const chunks = [];
      const recorderOptions = { videoBitsPerSecond: 2500000 };
      if (mimeType) recorderOptions.mimeType = mimeType;
      const recorder = new MediaRecorder(stream, recorderOptions);
      let settled = false;

      const fail = (error) => {
        if (settled) return;
        settled = true;
        stream.getTracks().forEach((track) => track.stop());
        reject(error);
      };

      recorder.addEventListener('dataavailable', (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      });
      recorder.addEventListener('error', () => fail(new Error('Canvas 素材錄製失敗。')), { once: true });
      recorder.addEventListener(
        'stop',
        () => {
          if (settled) return;
          settled = true;
          stream.getTracks().forEach((track) => track.stop());
          if (chunks.length === 0) {
            reject(new Error('Canvas 素材沒有產生可用畫面。'));
            return;
          }
          resolve(new Blob(chunks, { type: recorder.mimeType || mimeType || 'video/webm' }));
        },
        { once: true },
      );

      recorder.start(250);
      window.setTimeout(() => {
        if (recorder.state === 'recording') {
          try {
            recorder.requestData();
          } catch {
            // Some mobile implementations do not support requestData reliably.
          }
          recorder.stop();
        }
      }, Math.min(12000, Math.max(1200, duration * 1000)));
    });

  const captureCanvasFallback = (canvas) =>
    new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => {
          if (blob) resolve(blob);
          else reject(new Error('無法建立說話畫面的備援影像。'));
        },
        'image/jpeg',
        0.9,
      );
    });

  const saveBuiltinMaterial = async (index, segment, requestId) => {
    const composite = builtinCanvasRefs.current[index];
    const canvas = composite?.canvas;

    if (!canvas) {
      updateSegmentState(index, { materialStatus: 'idle', materialError: '說話畫面預覽尚未準備好。' });
      return;
    }

    updateSegmentState(index, { materialStatus: 'rendering', material: null, materialError: '' });

    try {
      const fallbackImage = await captureCanvasFallback(canvas);
      let clip = null;

      try {
        clip = await recordCanvasClip(canvas, composite.duration);
      } catch {
        // A still fallback keeps composition working when a mobile browser
        // emits an empty or timestamp-less MediaRecorder file.
      }

      if (builtinMaterialRequestRefs.current[index] !== requestId) return;

      const formData = new FormData();
      if (clip) {
        const extension = clip.type.includes('mp4') ? 'mp4' : 'webm';
        formData.append('video', clip, `builtin-material-${Date.now()}.${extension}`);
      }
      formData.append('fallback_image', fallbackImage, `builtin-material-${Date.now()}.jpg`);
      const res = await api.post('/api/builtin-materials/', formData);

      if (builtinMaterialRequestRefs.current[index] !== requestId) return;

      updateSegmentState(index, {
        materialStatus: 'ready',
        material: {
          type: 'builtin',
          videoUrl: res.data.videoUrl || '',
          fallbackImageUrl: res.data.fallbackImageUrl || '',
          loop: true,
        },
        materialError: '',
      });
    } catch (error) {
      if (builtinMaterialRequestRefs.current[index] !== requestId) return;

      updateSegmentState(index, {
        materialStatus: 'idle',
        material: null,
        materialError: error.response?.data?.detail || error.message || '說話畫面儲存失敗，請再試一次。',
      });
    }
  };

  const scheduleBuiltinMaterialSave = (index, segment) => {
    if (!canSaveBuiltinMaterial(segment, videoFormat)) return;

    const requestId = (builtinMaterialRequestRefs.current[index] || 0) + 1;
    builtinMaterialRequestRefs.current[index] = requestId;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => saveBuiltinMaterial(index, segment, requestId));
    });
  };

  const updateMaterialSource = (index, materialSource) => {
    const currentSegment = segmentsRef.current[index] || segments[index];
    const hasOtherTalkingSegment = segmentsRef.current.some(
      (segment, segmentIndex) => segmentIndex !== index && segment.materialSource === 'builtin',
    );
    if (materialSource === 'external' && !hasOtherTalkingSegment) {
      talkingCompositeRef.current = null;
    }
    const composite = talkingCompositeRef.current;
    const compositeReady = Boolean(
      materialSource === 'builtin' &&
      composite &&
      composite.characterId === selectedBuiltinCharacter &&
      composite.sceneId === selectedBuiltinScene &&
      composite.videoFormat === videoFormat,
    );
    const nextSegment = {
      ...currentSegment,
      materialSource,
      builtinCharacter: selectedBuiltinCharacter,
      builtinScene: selectedBuiltinScene,
      builtinCompositeKey: compositeReady
        ? `${selectedBuiltinCharacter}|${selectedBuiltinScene}|${videoFormat}`
        : '',
      materialStatus: 'idle',
      material: null,
      showMaterial: false,
      materialError: '',
    };
    const shouldSave = materialSource === 'builtin' && canSaveBuiltinMaterial(nextSegment, videoFormat);

    resetResultVideo();
    builtinMaterialRequestRefs.current[index] = (builtinMaterialRequestRefs.current[index] || 0) + 1;
    builtinCanvasRefs.current[index] = compositeReady ? composite : null;
    setSegments((currentSegments) =>
      currentSegments.map((segment, segmentIndex) =>
        segmentIndex === index
          ? { ...nextSegment, materialStatus: shouldSave ? 'rendering' : 'idle' }
          : segment,
      ),
    );

    if (shouldSave) scheduleBuiltinMaterialSave(index, nextSegment);
  };

  const handleTalkingCompositeReady = (composite) => {
    if (
      composite.characterId !== selectedBuiltinCharacter ||
      composite.sceneId !== selectedBuiltinScene ||
      composite.videoFormat !== videoFormat
    ) {
      return;
    }

    talkingCompositeRef.current = composite;
    setSegments((currentSegments) =>
      currentSegments.map((segment, index) => {
        if (segment.materialSource !== 'builtin') return segment;

        builtinCanvasRefs.current[index] = composite;
        return {
          ...segment,
          builtinCharacter: selectedBuiltinCharacter,
          builtinScene: selectedBuiltinScene,
          builtinCompositeKey: `${selectedBuiltinCharacter}|${selectedBuiltinScene}|${videoFormat}`,
          materialStatus: segment.audioUrl ? 'rendering' : 'idle',
          materialError: '',
        };
      }),
    );

    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        segmentsRef.current.forEach((segment, index) => {
          if (segment.materialSource === 'builtin') scheduleBuiltinMaterialSave(index, segment);
        });
      });
    });
  };

  const handleTalkingAnimationError = (error) => {
    talkingCompositeRef.current = null;
    setSegments((currentSegments) =>
      currentSegments.map((segment, index) => {
        if (segment.materialSource !== 'builtin') return segment;
        builtinCanvasRefs.current[index] = null;
        return {
          ...segment,
          builtinCompositeKey: '',
          materialStatus: 'idle',
          material: null,
          materialError: error?.message || '角色動畫載入失敗。',
        };
      }),
    );
  };

  const updateSegmentState = (index, nextValues) => {
    setSegments((currentSegments) =>
      currentSegments.map((segment, segmentIndex) =>
        segmentIndex === index ? { ...segment, ...nextValues } : segment,
      ),
    );
  };

  const getAudioDuration = (audioUrl) =>
    new Promise((resolve) => {
      const audio = new Audio(audioUrl);
      audio.addEventListener('loadedmetadata', () => resolve(audio.duration), { once: true });
      audio.addEventListener('error', () => resolve(0), { once: true });
    });

  const generateSegmentAudio = async (index) => {
    resetResultVideo();
    const segment = segments[index];

    if (!segment.text.trim()) {
      updateSegmentState(index, { error: '請先輸入片段內容。' });
      return;
    }

    updateSegmentState(index, { status: 'generating', error: '' });

    try {
      const res = await api.post(
        '/api/tts/',
        { text: segment.text, voice },
        { responseType: 'blob' },
      );
      const audioUrl = URL.createObjectURL(res.data);
      const duration = await getAudioDuration(audioUrl);
      const latestSegment = segmentsRef.current[index] || segment;
      const nextSegment = { ...latestSegment, audioUrl, duration };
      const shouldSaveBuiltinMaterial =
        nextSegment.materialSource === 'builtin' &&
        canSaveBuiltinMaterial(nextSegment, videoFormat);

      updateSegmentState(index, {
        status: 'ready',
        audioUrl,
        duration,
        size: res.data.size,
        materialStatus: shouldSaveBuiltinMaterial ? 'rendering' : 'idle',
        material: null,
        showMaterial: false,
        error: '',
        materialError: '',
      });

      if (shouldSaveBuiltinMaterial) scheduleBuiltinMaterialSave(index, nextSegment);
    } catch (error) {
      let errorMessage = '音檔生成失敗，請稍後再試。';

      if (error.response?.data instanceof Blob) {
        const text = await error.response.data.text();

        try {
          errorMessage = JSON.parse(text).detail || errorMessage;
        } catch {
          errorMessage = text || errorMessage;
        }
      } else if (error.response?.data?.detail) {
        errorMessage = error.response.data.detail;
      }

      updateSegmentState(index, { status: 'idle', error: errorMessage });
    }
  };

  const playSegmentAudio = (audioUrl) => {
    const audio = new Audio(audioUrl);
    audio.play();
  };

  const handleSegmentAction = (index) => {
    const segment = segments[index];

    if (segment.audioUrl) {
      playSegmentAudio(segment.audioUrl);
      return;
    }

    generateSegmentAudio(index);
  };

  const searchMaterial = async (index, replace = false) => {
    const segment = segments[index];

    if (segment.material && !replace) {
      updateSegmentState(index, { showMaterial: !segment.showMaterial, materialError: '' });
      return;
    }

    if (!segment.audioUrl || !segment.duration) {
      updateSegmentState(index, { materialError: '請先生成音檔。' });
      return;
    }

    if (!segment.keyword.trim()) {
      updateSegmentState(index, { materialError: '請輸入素材關鍵字。' });
      return;
    }

    resetResultVideo();
    updateSegmentState(index, { materialStatus: 'searching', materialError: '' });

    try {
      const res = await api.post('/api/pixabay/video/', {
        keyword: segment.keyword,
        min_duration: segment.duration,
        exclude_ids: segment.materialIds,
      });

      updateSegmentState(index, {
        materialStatus: 'ready',
        material: res.data,
        materialIds: [...segment.materialIds, res.data.id],
        showMaterial: true,
        materialError: '',
      });
    } catch (error) {
      updateSegmentState(index, {
        materialStatus: 'idle',
        materialError: error.response?.data?.detail || '素材搜尋失敗，請稍後再試。',
      });
    }
  };

  const composeVideo = async () => {
    setComposeStatus('composing');
    setComposeError('');

    const invalidSegmentIndex = segments.findIndex(
      (segment) =>
        !segment.text.trim() ||
        !segment.audioUrl ||
        (segment.materialSource === 'builtin'
          ? !segment.builtinScene ||
            (!segment.material?.videoUrl && !segment.material?.fallbackImageUrl)
          : !segment.material?.videoUrl),
    );

    if (invalidSegmentIndex >= 0) {
      setComposeStatus('idle');
      setComposeError(`片段 ${invalidSegmentIndex + 1} 需要先生成音檔並選擇素材。`);
      return;
    }

    try {
      const res = await api.post(
        '/api/video/compose/',
        {
          voice,
          video_format: videoFormat,
          segments: segments.map((segment) => ({
            text: segment.text,
            duration: segment.duration,
            materialType: segment.materialSource,
            videoUrl: segment.material?.videoUrl || '',
            fallbackImageUrl: segment.material?.fallbackImageUrl || '',
            loopMaterial: segment.materialSource === 'builtin',
            builtinScene: segment.builtinScene,
          })),
        },
        { responseType: 'blob' },
      );
      const videoUrl = URL.createObjectURL(res.data);

      if (resultVideoUrlRef.current) {
        URL.revokeObjectURL(resultVideoUrlRef.current);
      }

      setResultVideoUrl(videoUrl);
      setComposeStatus('ready');
    } catch (error) {
      let errorMessage = '影片合成失敗，請稍後再試。';

      if (error.response?.data instanceof Blob) {
        const text = await error.response.data.text();

        try {
          errorMessage = JSON.parse(text).detail || errorMessage;
        } catch {
          errorMessage = text || errorMessage;
        }
      } else if (error.response?.data?.detail) {
        errorMessage = error.response.data.detail;
      }

      setComposeStatus('idle');
      setComposeError(errorMessage);
    }
  };

  const handleExtraSegmentCount = (value) => {
    const nextValue = Number(value);

    if (Number.isNaN(nextValue)) {
      setExtraSegmentCount(1);
      return;
    }

    setExtraSegmentCount(Math.min(20, Math.max(1, nextValue)));
    setWorkflowStep(1);
  };

  const showScenePicker = () => {
    const nextSegmentCount = extraSegmentCount;

    if (nextSegmentCount !== segmentCount) {
      resetResultVideo();
      setSegmentCount(nextSegmentCount);
    }

    setWorkflowStep(2);
  };

  const selectBuiltinScene = (sceneId) => {
    if (sceneId === selectedBuiltinScene) return;

    resetResultVideo();
    talkingCompositeRef.current = null;
    setSelectedBuiltinScene(sceneId);
    setSegments((currentSegments) =>
      currentSegments.map((segment, index) => {
        builtinMaterialRequestRefs.current[index] =
          (builtinMaterialRequestRefs.current[index] || 0) + 1;
        builtinCanvasRefs.current[index] = null;

        if (segment.materialSource !== 'builtin') {
          return { ...segment, builtinScene: sceneId, builtinCompositeKey: '' };
        }

        return {
          ...segment,
          builtinScene: sceneId,
          builtinCompositeKey: '',
          materialStatus: 'idle',
          material: null,
          showMaterial: false,
          materialError: '',
        };
      }),
    );
  };

  const selectBuiltinCharacter = (characterId) => {
    if (characterId === selectedBuiltinCharacter) return;

    resetResultVideo();
    talkingCompositeRef.current = null;
    setSelectedBuiltinCharacter(characterId);
    setSegments((currentSegments) =>
      currentSegments.map((segment, index) => {
        builtinMaterialRequestRefs.current[index] =
          (builtinMaterialRequestRefs.current[index] || 0) + 1;
        builtinCanvasRefs.current[index] = null;

        if (segment.materialSource !== 'builtin') {
          return { ...segment, builtinCharacter: characterId, builtinCompositeKey: '' };
        }

        return {
          ...segment,
          builtinCharacter: characterId,
          builtinCompositeKey: '',
          materialStatus: 'idle',
          material: null,
          showMaterial: false,
          materialError: '',
        };
      }),
    );
  };

  const showSegmentEditor = () => {
    if (!selectedBuiltinCharacter || !selectedBuiltinScene) return;

    setSegments((currentSegments) =>
      currentSegments.map((segment) => ({
        ...segment,
        builtinCharacter: selectedBuiltinCharacter,
        builtinScene: selectedBuiltinScene,
        builtinCompositeKey: '',
      })),
    );
    talkingCompositeRef.current = null;
    setWorkflowStep(3);
  };

  const getMaterialButtonText = (segment) => {
    if (segment.materialStatus === 'searching') return '搜尋中...';
    if (segment.material) return segment.showMaterial ? '隱藏素材' : '觀看素材';
    return '選擇素材';
  };

  const handleMaterialPlay = (event) => {
    if (event.currentTarget.currentTime > 0.1) {
      event.currentTarget.currentTime = 0;
    }
  };

  const handleMaterialTimeUpdate = (event, trimEnd) => {
    if (event.currentTarget.currentTime >= trimEnd) {
      event.currentTarget.pause();
      event.currentTarget.currentTime = 0;
    }
  };

  const handleMaterialLoadedMetadata = (event) => {
    event.currentTarget.currentTime = 0;
  };

  const areSegmentsReadyToCompose =
    segments.length > 0 &&
    segments.every(
      (segment) =>
        segment.status === 'ready' &&
        Boolean(segment.audioUrl) &&
        segment.materialStatus === 'ready' &&
        (segment.materialSource === 'builtin'
          ? Boolean(
              segment.builtinCharacter &&
              segment.builtinScene &&
              segment.builtinCompositeKey === getBuiltinCompositeKey(segment, videoFormat) &&
              segment.material?.videoUrl,
            )
          : Boolean(segment.material?.videoUrl)),
    );
  const isPreparingSegments = segments.some(
    (segment) =>
      segment.status === 'generating' ||
      segment.materialStatus === 'rendering' ||
      segment.materialStatus === 'searching',
  );

  const selectedSceneName =
    builtInScenes.find((scene) => scene.id === selectedBuiltinScene)?.name || '';
  const selectedCharacterName =
    builtInCharacters.find((character) => character.id === selectedBuiltinCharacter)?.name || '';

  return (
    <main className="workspace-page">
      <section className="task-form">
        {workflowStep === 1 && <aside className="settings-panel">
          <p className="workflow-step-label">步驟 1 / 3 · 基本設定</p>
          <label htmlFor="voice">選擇聲音</label>
          <select
            id="voice"
            name="voice"
            value={voice}
            onChange={(e) => {
              resetResultVideo();
              setVoice(e.target.value);
            }}
            required
          >
            {voices.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>

          <label htmlFor="segmentCount">選擇片段數量</label>
          <div className="segment-count-row">
            <button
              type="button"
              className="segment-count-button"
              aria-label="減少片段數量"
              onClick={() => handleExtraSegmentCount(extraSegmentCount - 1)}
              disabled={extraSegmentCount <= 1}
            >
              −
            </button>
            <input
              type="number"
              id="segmentCount"
              name="segmentCount"
              value={extraSegmentCount}
              onChange={(e) => handleExtraSegmentCount(e.target.value)}
              inputMode="numeric"
              min="1"
              max="20"
              step="1"
              aria-label="片段數量，最少 1 段，最多 20 段"
            />
            <button
              type="button"
              className="segment-count-button"
              aria-label="增加片段數量"
              onClick={() => handleExtraSegmentCount(extraSegmentCount + 1)}
              disabled={extraSegmentCount >= 20}
            >
              ＋
            </button>
          </div>

          <label htmlFor="videoFormat">選擇影片尺寸</label>
          <select
            id="videoFormat"
            name="videoFormat"
            value={videoFormat}
            onChange={(e) => {
              resetResultVideo();
              setWorkflowStep(1);
              setVideoFormat(e.target.value);
            }}
          >
            {videoFormats.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <button type="button" className="next-step-button" onClick={showScenePicker}>
            下一步
          </button>
        </aside>}

        {workflowStep === 2 && <section className="scene-step-panel">
          <div className="scene-step-heading">
            <p className="workflow-step-label">步驟 2 / 3 · 選擇角色與場景</p>
            <p>選定的角色與場景會套用到第三步所有「說話畫面」片段。</p>
          </div>
          <section className="selection-block">
            <div className="selection-block-heading">
              <h2>選擇角色</h2>
              <p>{selectedCharacterName ? `已選擇：${selectedCharacterName}` : '請選擇一個角色'}</p>
            </div>
            <div className="material-choice-grid material-choice-grid--characters">
              {builtInCharacters.map((character) => (
                <button
                  type="button"
                  key={character.id}
                  className={`material-choice ${selectedBuiltinCharacter === character.id ? 'is-selected' : ''}`}
                  onClick={() => selectBuiltinCharacter(character.id)}
                >
                  <BuiltInMaterialCanvas
                    characterId={character.id}
                    sceneId={selectedBuiltinScene || 'classroom'}
                    videoFormat={videoFormat}
                    animate={false}
                    className={`material-choice-canvas material-choice-canvas--${videoFormat}`}
                  />
                  <span>{character.name}</span>
                </button>
              ))}
            </div>
          </section>
          <section className="selection-block">
            <div className="selection-block-heading">
              <h2>選擇場景</h2>
              <p>{selectedSceneName ? `已選擇：${selectedSceneName}` : '請選擇一個場景'}</p>
            </div>
            <div className="material-choice-grid material-choice-grid--scenes">
              {builtInScenes.map((scene) => (
                <button
                  type="button"
                  key={scene.id}
                  className={`material-choice ${selectedBuiltinScene === scene.id ? 'is-selected' : ''}`}
                  onClick={() => selectBuiltinScene(scene.id)}
                >
                  <BuiltInMaterialCanvas
                    characterId={selectedBuiltinCharacter || 'rabbit'}
                    sceneId={scene.id}
                    videoFormat={videoFormat}
                    animate={false}
                    className={`material-choice-canvas material-choice-canvas--${videoFormat}`}
                  />
                  <span>{scene.name}</span>
                </button>
              ))}
            </div>
          </section>
          <div className="workflow-actions">
            <button type="button" className="back-step-button" onClick={() => setWorkflowStep(1)}>
              上一步
            </button>
            <button
              type="button"
              className="next-step-button"
              onClick={showSegmentEditor}
              disabled={!selectedBuiltinCharacter || !selectedBuiltinScene}
            >
              下一步
            </button>
          </div>
        </section>}

        {workflowStep === 3 && <section className="work-panel">
          <p className="workflow-step-label">步驟 3 / 3 · 片段與素材</p>
          {segments.some((segment) => segment.materialSource === 'builtin') && (
            <section className="talking-scene-summary">
              <div>
                <h2>說話畫面</h2>
                <p>統一使用「{selectedCharacterName}」角色與「{selectedSceneName}」場景。</p>
              </div>
              <div className={`talking-scene-preview talking-scene-preview--${videoFormat}`}>
                <BuiltInMaterialCanvas
                  characterId={selectedBuiltinCharacter}
                  sceneId={selectedBuiltinScene}
                  videoFormat={videoFormat}
                  onAnimationError={handleTalkingAnimationError}
                  onCompositeReady={handleTalkingCompositeReady}
                  className="builtin-material-canvas"
                />
              </div>
            </section>
          )}
          <div className="segment-list">
            {segments.map((segment, index) => (
              <div className="segment-row" key={index}>
                <label htmlFor={`segment-${index}`}>片段 {index + 1}</label>
                <div className="segment-controls">
                  <input
                    type="text"
                    id={`segment-${index}`}
                    value={segment.text}
                    onChange={(e) => updateSegmentText(index, e.target.value)}
                    placeholder="請輸入這段旁白內容"
                  />
                  <button
                    type="button"
                    className="segment-button"
                    onClick={() => handleSegmentAction(index)}
                    disabled={segment.status === 'generating'}
                  >
                    {segment.status === 'generating'
                      ? '生成中...'
                      : segment.audioUrl
                        ? `${formatDuration(segment.duration)} / ${formatFileSize(segment.size)}`
                        : '生成音檔'}
                  </button>
                </div>
                <div className="material-source-area">
                  <label htmlFor={`material-source-${index}`}>選擇素材</label>
                  <select
                    id={`material-source-${index}`}
                    value={segment.materialSource}
                    onChange={(e) => updateMaterialSource(index, e.target.value)}
                  >
                    <option value="builtin">說話畫面</option>
                    <option value="external">外部素材</option>
                  </select>

                  {segment.materialSource === 'external' && (
                    <div className="external-material-controls">
                      <input
                        type="text"
                        className="keyword-input"
                        value={segment.keyword}
                        onChange={(e) => updateSegmentKeyword(index, e.target.value)}
                        placeholder="關鍵字"
                      />
                      <button
                        type="button"
                        className="material-button"
                        onClick={() => searchMaterial(index)}
                        disabled={segment.materialStatus === 'searching'}
                      >
                        {getMaterialButtonText(segment)}
                      </button>
                    </div>
                  )}
                  {segment.materialSource === 'builtin' && (
                    <p className="talking-scene-note">
                      使用第二步選擇的「{selectedCharacterName}」與「{selectedSceneName}」說話畫面。
                      {segment.materialStatus === 'rendering' && ' 正在準備素材...'}
                    </p>
                  )}
                </div>
                {segment.error && <p className="segment-error">{segment.error}</p>}
                {segment.materialError && <p className="segment-error">{segment.materialError}</p>}
                {segment.showMaterial && segment.material && (
                  <div className="material-preview">
                    <video
                      src={getTrimmedVideoUrl(segment.material.videoUrl, segment.material.trimEnd)}
                      poster={segment.material.thumbnail}
                      controls
                      onLoadedMetadata={handleMaterialLoadedMetadata}
                      onPlay={handleMaterialPlay}
                      onTimeUpdate={(event) => handleMaterialTimeUpdate(event, segment.material.trimEnd)}
                    />
                    <button
                      type="button"
                      className="replace-material-button"
                      onClick={() => searchMaterial(index, true)}
                      disabled={segment.materialStatus === 'searching'}
                    >
                      更換素材
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="compose-panel">
            <div className="compose-actions">
              <button
                type="button"
                className="back-step-button"
                onClick={() => setWorkflowStep(2)}
                disabled={composeStatus === 'composing'}
              >
                上一步
              </button>
              <button
                type="button"
                className="compose-button"
                onClick={composeVideo}
                disabled={!areSegmentsReadyToCompose || composeStatus === 'composing'}
              >
                {composeStatus === 'composing'
                  ? '合成中...'
                  : isPreparingSegments
                    ? '準備素材中...'
                    : '合成影片'}
              </button>
            </div>
            {!areSegmentsReadyToCompose && (
              <p className="compose-status-message">
                {isPreparingSegments
                  ? '正在準備音檔或素材，完成後即可合成。'
                  : '請先完成每個片段的音檔與素材。'}
              </p>
            )}
            {composeError && <p className="segment-error">{composeError}</p>}
            {resultVideoUrl && (
              <div className={`result-preview result-preview--${videoFormat}`}>
                <video src={resultVideoUrl} controls />
              </div>
            )}
          </div>
        </section>}
      </section>
    </main>
  );
}

export default Home;
