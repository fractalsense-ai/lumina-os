"""lumina.daemon — Resource Monitor Daemon package.

Public surface
--------------
- ``load_estimator``   – weighted load-score aggregator (``LoadEstimator``,
  ``LoadSnapshot``)
- ``preemption``       – cooperative yielding protocol (``PreemptionToken``,
  ``TaskPreempted``)
- ``resource_monitor`` – the daemon itself (``ResourceMonitorDaemon``,
  ``start``, ``stop``, ``is_running``, ``get_status``)
- ``task_adapter``     – bridge between daemon dispatch and task functions
- ``tasks``            – task implementations
- ``report``           – task result and proposal data classes
- ``scheduler``        – task scheduler with run history and proposals
- ``cross_domain``     – cross-domain synthesis analysis
"""
