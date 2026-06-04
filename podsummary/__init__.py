"""podsummary: summarise Spotify podcasts via matched YouTube transcripts and OpenAI.

The package is organised into small, individually testable modules:

* :mod:`podsummary.config`       - configuration loading (YAML + environment)
* :mod:`podsummary.models`       - plain dataclasses passed between stages
* :mod:`podsummary.spotify_client` - list Spotify episodes for a show/period
* :mod:`podsummary.youtube_client` - list YouTube videos for a channel/period
* :mod:`podsummary.transcripts`  - pluggable transcript retrieval
* :mod:`podsummary.matching`     - fuzzy title + date-window episode<->video matching
* :mod:`podsummary.prompts`      - prompt templates
* :mod:`podsummary.summariser`   - per-episode and period (weekly) summarisation
* :mod:`podsummary.pipeline`     - end-to-end orchestration
* :mod:`podsummary.cli`          - command line entry point
"""

__version__ = "0.1.0"
