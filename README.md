# GitHub Contribution

GitHubの活動履歴を、最新年から過去年へ続く縦長の草マップにします。
[![profile-dark.webp](../contribution-graphs/profile-dark3.webp#gh-dark-mode-only)](../contribution-graphs/profile-dark.webp#gh-dark-mode-only) \
[![profile-light.webp](../contribution-graphs/profile-light3.webp#gh-light-mode-only)](../contribution-graphs/profile-light.webp#gh-light-mode-only)

[全体画像：黒](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-dark.webp) · [全体画像：白](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-light.webp) · [ダイアログHTMLをダウンロード](https://github.com/DaisukeDaisuke/github-contribution/raw/refs/heads/contribution-graphs/dialog.html)


## Activity statistics

[![activity-dark.webp](../contribution-graphs/activity-dark3.webp#gh-dark-mode-only)](../contribution-graphs/activity-dark.webp#gh-dark-mode-only) \
[![activity-light.webp](../contribution-graphs/activity-light3.webp#gh-light-mode-only)](../contribution-graphs/activity-light.webp#gh-light-mode-only)

草画像とは別に、PRの作成・マージ・Open・未マージClose、Issueの作成・Open・Close、レビューしたPR数、公開リポジトリ数・アーカイブ数・Stars・Forks・Release数、Followers、言語分布を表示します。プレビューをクリックすると全体画像を開きます。

公開データのみを集計します。PR・Issueは本人が作成したもの、レビューはレビューしたPRの重複なし件数です。リポジトリ集計と言語分布は所有する公開・非forkリポジトリが対象です。言語の割合はGitHubが検出したバイト数で、本人が書いた行数ではありません。

通常はGraphQL 1回（100リポジトリまで）で統計を取得します。それ以上は100件ずつ直列取得し、通信完了後に1.2秒以上あけます。上限は49回とアイコン取得1回の計50回。上限で打ち切った場合は画像に`PARTIAL SAMPLE`と集計対象数を表示します。

統計はユーザー別・UTCのISO週（年＋週番号）別のActionsキャッシュへ保存し、同じ週の再実行はAPI取得0回。週が変わったら統計を更新し、URLが同じアイコンは前回のキャッシュを再利用します。キャッシュが削除された場合は再取得します。**活動統計のAPI応答・キャッシュJSONは生成ブランチやPagesへ公開しません。**

## できること

- 対象ユーザーのアカウント作成年から実行日までを1つの表に表示。最新年が上、過去年が下。左側に年、右側に曜日を表示します。
- ライト・ダークのSVG・PNG・ロスレスWebPと、高さ600pxで下端をフェードさせたプレビューを生成します。
- ダイアログHTMLではプレビューをクリックして全体を表示。単独HTMLとしてブラウザーで開けます。
- 通常のHTMLでは日別件数の確認、日付選択、CSV・JSONの保存ができます。
- ヘッダーの`xx days`で、活動が1件以上あった日数の合計を表示します。
- GitHub Actionsで毎月1日09:17 JSTに更新し、画像・HTML・データを`contribution-graphs`ブランチに保存します。
- 外部保存の指定なしなら生成用リポジトリのみ、指定ありなら生成用と指定先の両方へ保存します。外部保存では既定ブランチへのpushとforce pushは禁止し、既存ブランチにはマークファイルを要求します。

## インストール・外部保存

[画像付きのセットアップ手順](install.md)に、`DEPLOY_REPOSITORY`・`DEPLOY_BRANCH`・`DEPLOY_TOKEN`の設定、マークファイルの条件、プロフィールREADMEからの参照方法をまとめています。
`DEPLOY_REPOSITORY`と`DEPLOY_BRANCH`はVariablesへ、**`DEPLOY_TOKEN`は必ずSecretsへ登録**します。<br>
トークンの値をVariables・README・コード・URLへ書かないでください。

## 自分の草マップを作る

1. [Use this template](https://github.com/DaisukeDaisuke/github-contribution/generate)からリポジトリを作成します。
2. 作成先の**Actions → Update contribution archive → Run workflow**を実行します。対象は既定でリポジトリ所有者です。別のユーザーを指定する場合は`github_user`に入力します。
3. 生成先の`contribution-graphs`ブランチにある`embed.md`のコードを、自分のREADMEに貼り付けます。初回実行後は毎月自動更新されます。

開始年は対象ユーザーのアカウント作成年、終了日は実行日から自動で決まります。APIは1年ずつ直列取得し、各通信の完了後に1.2秒以上あけます。
実行年の2年前以前は、`2021.json`のような年ごとのファイルをGitHub Actionsキャッシュへ固定キーで保存します。キャッシュがある年はAPIから取得せず、当年と前年は毎回取得します。キーはユーザー・取得元・年で分離します。

## 設定

**Settings → Secrets and variables → Actions → Variables**で変更できます。

|変数|既定値|用途|
|---|---|---|
|`CONTRIBUTION_USER`|リポジトリ所有者|生成対象のGitHubユーザー名|
|`START_YEAR`|アカウント作成年|必要な場合だけ取得開始年を指定|
|`ENABLE_PAGES`|未設定|`true`でHTMLをGitHub Pagesに公開|

Pagesを使う場合は**Settings → Pages → Source**も**GitHub Actions**に設定し、Run workflowを実行します。公開先の`/`が全体表示、`/dialog.html`がダイアログです。

## 出力

[生成物一覧](https://github.com/DaisukeDaisuke/github-contribution/tree/contribution-graphs)に両テーマの全体画像・プレビュー、HTML、日別・年別・月別CSV、`data.json`、READMEに貼り付けるための`embed.md`を保存します。
ダイアログのHTMLテンプレートは[templates/dialog.html](templates/dialog.html)です。
