"""Integration tests for sentinel init command (v1.0)."""

import pytest
import shutil
from pathlib import Path

from sentinel.cli import cmd_init


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def example_files(config_dir):
    """Create example config files."""
    sources_example = config_dir / "sources.example.yaml"
    suppression_example = config_dir / "suppression.example.yaml"
    
    sources_example.write_text("version: 1\ndefaults:\n  enabled: true\n")
    suppression_example.write_text("version: 1\nenabled: true\nrules: []\n")
    
    return sources_example, suppression_example


def test_init_creates_config_files(config_dir, example_files, monkeypatch):
    """Test that sentinel init creates config files from examples."""
    sources_example, suppression_example = example_files
    
    # Mock Path to use our temp directory
    original_path = Path
    def mock_path(path_str):
        if path_str == "config":
            return config_dir
        return original_path(path_str)
    
    monkeypatch.setattr("sentinel.cli.Path", mock_path)
    
    # Create args namespace
    class Args:
        force = False
    
    args = Args()
    
    # Run init
    cmd_init(args)
    
    # Verify files were created
    sources_config = config_dir / "sources.yaml"
    suppression_config = config_dir / "suppression.yaml"
    
    assert sources_config.exists()
    assert suppression_config.exists()
    
    # Verify content matches examples
    assert sources_config.read_text() == sources_example.read_text()
    assert suppression_config.read_text() == suppression_example.read_text()


def test_init_skips_existing_files(config_dir, example_files, monkeypatch):
    """Test that sentinel init skips existing files unless --force."""
    sources_example, suppression_example = example_files
    
    # Create existing config files
    sources_config = config_dir / "sources.yaml"
    suppression_config = config_dir / "suppression.yaml"
    sources_config.write_text("existing content")
    suppression_config.write_text("existing content")
    
    # Mock Path
    original_path = Path
    def mock_path(path_str):
        if path_str == "config":
            return config_dir
        return original_path(path_str)
    
    monkeypatch.setattr("sentinel.cli.Path", mock_path)
    
    # Create args namespace
    class Args:
        force = False
    
    args = Args()
    
    # Run init
    cmd_init(args)
    
    # Verify existing files were not overwritten
    assert sources_config.read_text() == "existing content"
    assert suppression_config.read_text() == "existing content"


def test_init_force_overwrites_existing_files(config_dir, example_files, monkeypatch):
    """Test that sentinel init --force overwrites existing files."""
    sources_example, suppression_example = example_files
    
    # Create existing config files
    sources_config = config_dir / "sources.yaml"
    suppression_config = config_dir / "suppression.yaml"
    sources_config.write_text("existing content")
    suppression_config.write_text("existing content")
    
    # Mock Path
    original_path = Path
    def mock_path(path_str):
        if path_str == "config":
            return config_dir
        return original_path(path_str)
    
    monkeypatch.setattr("sentinel.cli.Path", mock_path)
    
    # Create args namespace
    class Args:
        force = True
    
    args = Args()
    
    # Run init
    cmd_init(args)
    
    # Verify files were overwritten with example content
    assert sources_config.read_text() == sources_example.read_text()
    assert suppression_config.read_text() == suppression_example.read_text()


def test_init_validates_yaml(config_dir, example_files, monkeypatch):
    """Test that created config files are valid YAML."""
    import yaml
    
    sources_example, suppression_example = example_files
    
    # Mock Path
    original_path = Path
    def mock_path(path_str):
        if path_str == "config":
            return config_dir
        return original_path(path_str)
    
    monkeypatch.setattr("sentinel.cli.Path", mock_path)
    
    # Create args namespace
    class Args:
        force = False
    
    args = Args()
    
    # Run init
    cmd_init(args)
    
    # Verify files are valid YAML
    sources_config = config_dir / "sources.yaml"
    suppression_config = config_dir / "suppression.yaml"
    
    # Should not raise exception
    yaml.safe_load(sources_config.read_text())
    yaml.safe_load(suppression_config.read_text())

