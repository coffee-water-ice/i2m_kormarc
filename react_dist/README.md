# react_dist/ — React 프론트 빌드 산출물 (커밋된 아티팩트)

`i2m_kormarc_react`(별도 비공개 GitHub 저장소)에서 `npm run build`로 만든 결과를
그대로 복사해 넣은 폴더다. 이 Dockerfile은 이 저장소(`i2m_kormarc`)만 빌드
컨텍스트로 보기 때문에, 별도 저장소인 React 소스를 직접 빌드할 수 없다 — 그래서
"미리 빌드해서 커밋해 둔 결과물"을 대신 넣어뒀다.

nginx가 이걸 `/app/` 경로로 서비스한다(`nginx.conf` 참고). React 쪽 `vite.config.ts`가
프로덕션 빌드에서 `base: '/app/'`을 쓰므로 자산 경로(`/app/assets/...`)가 이미 여기
맞춰져 있다.

## 갱신 방법

React 쪽을 고친 뒤 배포에 반영하려면 **수동으로 다시 복사**해야 한다(자동 빌드
아님):

```bash
cd i2m_kormarc_react
npm run build
rm -rf ../i2m_kormarc/react_dist/*
cp -r dist/* ../i2m_kormarc/react_dist/
```

그 다음 `i2m_kormarc`에서 이 변경을 커밋 — 다른 파일과 마찬가지로 브랜치에서
작업하고 main에 머지해야 실제로 배포된다.

## 왜 Docker 이미지 안에서 직접 빌드하지 않는가

React 소스가 별도 비공개 저장소라, 이 방법 말고는 (a) 빌드 시점에 그 저장소를
GitHub 토큰으로 clone하는 방법이 있는데, Space Secret을 하나 더 늘리고 빌드마다
Node.js 설치+npm install까지 해야 해서 이미지가 커지고 빌드가 느려진다. 지금은
React 쪽 변경이 자주 일어나지 않는 단계라, 그 복잡도 대신 "빌드해서 커밋"을
택했다 — 나중에 변경 빈도가 늘면 (a) 방식으로 바꾸는 걸 고려할 것.
