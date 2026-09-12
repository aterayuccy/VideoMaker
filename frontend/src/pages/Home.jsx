import { useEffect, useRef, useState } from 'react';
import api from '../api';
import '../styles/Home.css';

const fallbackVoices = [
  { id: 'zh-TW-HsiaoChenNeural', name: '曉臻（台灣女聲）' },
  { id: 'zh-TW-YunJheNeural', name: '雲哲（台灣男聲）' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '曉曉（中文女聲）' },
  { id: 'zh-CN-YunxiNeural', name: '雲希（中文男聲）' },
  { id: 'en-US-JennyNeural', name: 'Jenny（英文女聲）' },
  { id: 'en-US-GuyNeural', name: 'Guy（英文男聲）' },
];

const createEmptySegment = () => ({
  text: '',
  status: 'idle',
  audioUrl: '',
  duration: 0,
  size: 0,
  keyword: '',
  materialStatus: 'idle',
  material: null,
  materialIds: [],
  materialHistory: [],
  materialIndex: -1,
  showMaterial: false,
  error: '',
  materialError: '',
});

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
  const segmentsRef = useRef(segments);
  const resultVideoUrlRef = useRef(resultVideoUrl);

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
        nextSegments.push(createEmptySegment());
      }

      currentSegments.slice(segmentCount).forEach((segment) => {
        if (segment.audioUrl) URL.revokeObjectURL(segment.audioUrl);
      });

      return nextSegments;
    });
  }, [segmentCount]);

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
          materialHistory: [],
          materialIndex: -1,
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
              materialHistory: [],
              materialIndex: -1,
              showMaterial: false,
              materialError: '',
            }
          : segment,
      ),
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

      updateSegmentState(index, {
        status: 'ready',
        audioUrl,
        duration,
        size: res.data.size,
        materialStatus: 'idle',
        material: null,
        showMaterial: false,
        error: '',
        materialError: '',
      });

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

  const searchMaterial = async (index) => {
    const segment = segments[index];

    if (segment.material) {
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
        materialHistory: [res.data],
        materialIndex: 0,
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

  const browseMaterial = async (index, direction) => {
    const segment = segmentsRef.current[index];
    const nextIndex = segment.materialIndex + direction;

    if (nextIndex >= 0 && nextIndex < segment.materialHistory.length) {
      resetResultVideo();
      updateSegmentState(index, {
        material: segment.materialHistory[nextIndex],
        materialIndex: nextIndex,
        showMaterial: true,
        materialError: '',
      });
      return;
    }

    if (direction < 0 || segment.materialStatus === 'searching') return;

    resetResultVideo();
    updateSegmentState(index, { materialStatus: 'searching', materialError: '' });

    try {
      const res = await api.post('/api/pixabay/video/', {
        keyword: segment.keyword,
        min_duration: segment.duration,
        exclude_ids: segment.materialIds,
      });
      const materialHistory = [...segment.materialHistory, res.data];

      updateSegmentState(index, {
        materialStatus: 'ready',
        material: res.data,
        materialIds: [...segment.materialIds, res.data.id],
        materialHistory,
        materialIndex: materialHistory.length - 1,
        showMaterial: true,
        materialError: '',
      });
    } catch (error) {
      updateSegmentState(index, {
        materialStatus: 'ready',
        materialError: error.response?.data?.detail || '找不到更多素材，請換個關鍵字。',
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
        !segment.material?.videoUrl,
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
            materialType: 'external',
            videoUrl: segment.material?.videoUrl || '',
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

  const showSegmentEditor = () => {
    const nextSegmentCount = extraSegmentCount;

    if (nextSegmentCount !== segmentCount) {
      resetResultVideo();
      setSegmentCount(nextSegmentCount);
    }

    setWorkflowStep(2);
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
        Boolean(segment.material?.videoUrl),
    );
  const isPreparingSegments = segments.some(
    (segment) =>
      segment.status === 'generating' ||
      segment.materialStatus === 'searching',
  );

  return (
    <main className="workspace-page">
      <section className="task-form">
        {workflowStep === 1 && <aside className="settings-panel">
          <p className="workflow-step-label">步驟 1 / 2 · 基本設定</p>
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
          <button type="button" className="next-step-button" onClick={showSegmentEditor}>
            下一步
          </button>
        </aside>}

        {workflowStep === 2 && <section className="work-panel">
          <p className="workflow-step-label">步驟 2 / 2 · 旁白與素材</p>
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
                  <label htmlFor={`material-keyword-${index}`}>搜尋影片素材</label>
                  <div className="external-material-controls">
                    <input
                      id={`material-keyword-${index}`}
                      type="text"
                      className="keyword-input"
                      value={segment.keyword}
                      onChange={(e) => updateSegmentKeyword(index, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') searchMaterial(index);
                      }}
                      placeholder="例如：海邊、咖啡、城市"
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
                </div>
                {segment.error && <p className="segment-error">{segment.error}</p>}
                {segment.materialError && <p className="segment-error">{segment.materialError}</p>}
                {segment.showMaterial && segment.material && (
                  <div
                    className="material-preview"
                    tabIndex="0"
                    onKeyDown={(event) => {
                      if (event.key === 'ArrowLeft') {
                        event.preventDefault();
                        browseMaterial(index, -1);
                      }
                      if (event.key === 'ArrowRight') {
                        event.preventDefault();
                        browseMaterial(index, 1);
                      }
                    }}
                    aria-label={`片段 ${index + 1} 素材預覽，可使用左右方向鍵更換素材`}
                  >
                    <video
                      src={getTrimmedVideoUrl(segment.material.videoUrl, segment.material.trimEnd)}
                      poster={segment.material.thumbnail}
                      controls
                      onLoadedMetadata={handleMaterialLoadedMetadata}
                      onPlay={handleMaterialPlay}
                      onTimeUpdate={(event) => handleMaterialTimeUpdate(event, segment.material.trimEnd)}
                    />
                    <div className="material-browser-controls">
                      <button
                        type="button"
                        className="material-arrow-button"
                        onClick={() => browseMaterial(index, -1)}
                        disabled={segment.materialIndex <= 0 || segment.materialStatus === 'searching'}
                        aria-label="上一個素材"
                      >
                        ←
                      </button>
                      <span aria-live="polite">
                        素材 {segment.materialIndex + 1}
                      </span>
                      <button
                        type="button"
                        className="material-arrow-button"
                        onClick={() => browseMaterial(index, 1)}
                        disabled={segment.materialStatus === 'searching'}
                        aria-label="下一個素材"
                      >
                        →
                      </button>
                    </div>
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
                onClick={() => setWorkflowStep(1)}
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
              <div className="result-area">
                <p className="result-title">影片已完成</p>
                <div className={`result-preview result-preview--${videoFormat}`}>
                  <video src={resultVideoUrl} controls />
                </div>
                <a
                  className="download-button"
                  href={resultVideoUrl}
                  download="video.mp4"
                >
                  下載影片
                </a>
              </div>
            )}
          </div>
        </section>}
      </section>
    </main>
  );
}

export default Home;
