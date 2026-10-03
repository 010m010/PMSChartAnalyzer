# 開発環境とチェック

このリポジトリには、アプリの依存を定義する `requirements.txt` と、テスト用の依存も含む `requirements-dev.txt` がある。開発作業には既存の `.venv` を使う。

## Windows

リポジトリのルートで実行する。

```powershell
.\setup.bat --dev
.\check.bat
```

通常のアプリ利用だけなら `setup.bat`、起動は `run.bat`。セットアップの失敗時は終了コードが非ゼロになり、完了メッセージは表示されない。

## macOS / Linux

```bash
bash setup.sh --dev
.venv/bin/python -B scripts/check.py
```

## チェック内容

`scripts/check.py` は、次を順に実行し、失敗した時点で非ゼロの終了コードを返す。GitHub Actions でも同じコマンドを Windows / Linux、Python 3.10 で実行する。

1. `.agents/skills-sources.json` と導入スキルの照合。意図しない追加スキル、マニフェスト、明示呼び出しの設定、文書の参照先、Python 構文、ライセンスを検証する。
2. UI/UX Pro Max の検索データの検証。
3. `tests/` の pytest テスト。アプリの既存テストに加え、セットアップの失敗処理とスキル検証の回帰テストを含む。

Windows では `check.bat --tests-only` または `check.bat --skills-only` で対象を絞れる。ほかの環境では `python scripts/check.py` に同じオプションを付ける。

## スキルの更新

導入元とバージョンは `.agents/skills-sources.json` に記録している。更新後は `scripts/check.py --skills-only` を実行する。公式インストーラーが追加するロゴ・バナー・スライド等の補助スキルは、このプロジェクトの導入対象に含まれていない。意図した追加ならマニフェストに記録し、意図しない追加なら除外する。

## GitHub

この環境では認証済みの GitHub コネクタを利用できる。Issue の操作先と手順は `docs/agents/issue-tracker.md` を参照する。コネクタを利用できない環境では、GitHub CLI を用意して `gh auth login` で認証する。
