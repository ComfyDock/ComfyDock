# Security Policy

## Supported Versions

ComfyGit is currently in active development (v1.x). Security updates are provided for the latest released version.

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of the following methods:

### Preferred: GitHub Security Advisories

1. Go to the [Security tab](https://github.com/comfygit-ai/comfygit/security/advisories/new)
2. Click "Report a vulnerability"
3. Provide details about the vulnerability

### Alternative: Email

If you prefer email, contact the maintainer directly:
- Open a regular issue requesting secure contact information
- Or contact via GitHub profile

### What to Include

Please include as much of the following information as possible:

- Type of vulnerability (e.g., code execution, information disclosure)
- Full paths of affected source files
- Location of the affected code (tag/branch/commit)
- Step-by-step instructions to reproduce
- Proof-of-concept or exploit code (if possible)
- Impact assessment
- Suggested fix (if you have one)

## Response Timeline

- **Acknowledgment**: Within 48 hours of report
- **Initial Assessment**: Within 1 week
- **Fix Timeline**: Varies by severity (see below)
- **Public Disclosure**: After fix is released and users have time to update

### Severity Levels

**Critical** (Fix within 7 days)
- Remote code execution
- Authentication bypass
- Data exposure of user credentials/keys

**High** (Fix within 14 days)
- Local code execution
- Significant privilege escalation
- Data exposure of sensitive workflow information

**Medium** (Fix within 30 days)
- Denial of service
- Information disclosure (non-sensitive)
- Limited privilege escalation

**Low** (Fix in next release)
- Security best practice improvements
- Minor information leaks

## Security Considerations

### ComfyGit's Security Model

ComfyGit is a **local development tool** that:
- Executes code from ComfyUI custom nodes (third-party Python packages)
- Downloads models from user-specified URLs
- Runs with the user's local permissions
- Does not expose network services (except when running ComfyUI itself)

**This means:**
- Users should trust the custom nodes they install
- Model downloads should be from trusted sources
- ComfyGit operates within your user's permission scope

### Not Security Vulnerabilities

The following are **expected behavior** and not security issues:

1. **Custom nodes executing arbitrary code** - This is intentional. ComfyGit installs Python packages that run with your permissions. Review nodes before installing.

2. **Model downloads from untrusted URLs** - Users explicitly provide URLs. We validate file integrity but cannot verify model safety.

3. **Git repository cloning** - When importing environments from git, you're trusting that repository. Review before importing.

4. **Local file system access** - ComfyGit needs to read/write files in its workspace. This is required functionality.

### Actual Security Concerns

Please **do report**:

1. **Command injection** - If user input can execute unintended shell commands
2. **Path traversal** - If ComfyGit can be tricked into accessing files outside its workspace
3. **Credential exposure** - If API keys or tokens are logged/leaked
4. **Malicious package installation** - If ComfyGit can be tricked into installing different packages than intended
5. **MITM vulnerabilities** - If downloads don't verify integrity properly

## Best Practices for Users

### Secure Usage

1. **Review before installing**
   ```bash
   # Check what a node is before adding it
   cfd node info <node-name>
   ```

2. **Use version control**
   ```bash
   # Commit before trying new nodes
   cfd commit -m "Before adding experimental-node"
   # Easy rollback if something goes wrong
   cfd rollback
   ```

3. **Verify model sources**
   - Download models from official sources (CivitAI, HuggingFace)
   - Check file hashes when available
   - Be cautious with direct file URLs

4. **Protect your API keys**
   ```bash
   # Store keys in config, not in exported environments
   cfd config --civitai-key YOUR_KEY
   ```

5. **Review imported environments**
   ```bash
   # Check what's in an environment before importing
   tar -tzf environment.tar.gz
   # Or preview git repo before cloning
   ```

### Secure Development

If you're building on ComfyGit Core:

1. **Validate user input** - Don't pass unsanitized input to shell commands
2. **Use the API properly** - Follow callback patterns, don't bypass safety checks
3. **Handle secrets carefully** - Never log API keys or credentials
4. **Verify downloads** - Check hashes when downloading files

## Disclosure Policy

### Coordinated Disclosure

- We follow coordinated disclosure practices
- Vulnerabilities are not disclosed until a fix is available
- We credit reporters (unless they prefer anonymity)
- We publish security advisories for fixed vulnerabilities

### Timeline

1. Report received and acknowledged
2. Vulnerability validated and severity assessed
3. Fix developed and tested
4. Security patch released
5. Security advisory published (7-14 days after release)
6. CVE requested if applicable

## Security Updates

Security updates are announced via:
- [GitHub Security Advisories](https://github.com/comfygit-ai/comfygit/security/advisories)
- Release notes in GitHub Releases
- Updates to this SECURITY.md file

Subscribe to the repository to receive notifications.

## Scope

### In Scope

- ComfyGit Core library (`comfygit_core`)
- ComfyGit CLI (`comfygit_cli`)
- Build and publishing infrastructure
- Documentation (if it could lead to insecure usage)

### Out of Scope

- ComfyUI itself (report to ComfyUI project)
- Third-party custom nodes (report to node authors)
- User's Python environment or system configuration
- External services (CivitAI, GitHub, PyPI)

## Contact

For security concerns that don't rise to the level of a vulnerability report, you can:
- Open a regular GitHub issue (for non-sensitive topics)
- Start a discussion in GitHub Discussions

Thank you for helping keep ComfyGit and its users safe!
