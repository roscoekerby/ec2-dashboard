# EC2 Dashboard

A desktop GUI application for managing AWS EC2 instances over SSH/SFTP. Built with Python and Tkinter.

## Features

- Connect to EC2 instances using a PEM key file
- Browse and navigate the remote filesystem
- Upload and download files
- Create folders, rename, and delete remote files
- View and edit remote files
- Integrated terminal with command history

## Requirements

- Python 3.8+
- An AWS EC2 instance with SSH access
- Your EC2 `.pem` key file (stored locally, never committed)

## Installation

```bash
git clone https://github.com/roscoekerby/ec2-dashboard.git
cd ec2-dashboard
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install paramiko pillow python-dotenv
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
EC2_HOST=your-ec2-public-ip
EC2_USERNAME=ubuntu
EC2_KEY_PATH=/path/to/your-key.pem
```

> `.env` is gitignored and will never be committed.

## Usage

```bash
python server.py
```

The app pre-fills the connection fields from your `.env`. You can also update the host, username, and key path directly in the UI, then click **Connect**.

## Security

- PEM key files and the `pems/` directory are excluded from version control via `.gitignore`
- All sensitive config lives in `.env` (gitignored)
- Never commit your `.pem` files or real credentials
