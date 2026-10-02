// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private readonly AsyncLocal<CancellationToken> pageReadToken=new AsyncLocal<CancellationToken>();
        private CancellationTokenSource pageReads=new CancellationTokenSource();
        private readonly Stopwatch monitoringClock=Stopwatch.StartNew();
        private long pageGeneration,nextGeneralRefresh,nextConsoleRefresh,nextPerformanceRefresh;
        private bool pageLoading;

        private static bool IsPageRead(string action){
            return action=="status"||action=="logs"||action=="logs.poll"||action=="monitoring.metrics"
                ||action.EndsWith(".get",StringComparison.Ordinal)||action.EndsWith(".list",StringComparison.Ordinal)
                ||action.EndsWith(".status",StringComparison.Ordinal)||action=="settings.capabilities"||action=="launch.settings";
        }
        private void CancelPageReads(){
            var previous=pageReads;pageReads=new CancellationTokenSource();pageGeneration++;
            previous.Cancel();previous.Dispose();pageLoading=false;nextGeneralRefresh=nextConsoleRefresh=nextPerformanceRefresh=0;
        }
        private void ConfigureMonitoringPoll(){
            int interval=loginPreferences.EffectiveRefreshMilliseconds;
            if(loginPreferences.HighPerformanceMonitoring&&inServerManagement){
                interval=Math.Min(interval,loginPreferences.PerformanceRefreshMilliseconds);
                if(currentPage=="console"||DetachedConsoleVisible)interval=Math.Min(interval,loginPreferences.ConsoleRefreshMilliseconds);
            }
            poll.Interval=Math.Max(1,Math.Min(60000,interval));
        }
        private async Task PollUiAsync(){
            if(refreshing||pageLoading||!MonitoringUiVisible||!authenticated||exiting)return;
            if(!loginPreferences.HighPerformanceMonitoring||!inServerManagement){await RefreshCurrentPageAsync();return;}
            if(pageRefresh==null)return;
            refreshing=true;long generation=pageGeneration;var token=pageReads.Token;var prior=pageReadToken.Value;pageReadToken.Value=token;
            try{
                activePageRefresh=PollMonitoringAsync(generation,token);await activePageRefresh;
            }catch(OperationCanceledException){}catch(Exception error){if(generation==pageGeneration)SetStatus(error.Message);}
            finally{pageReadToken.Value=prior;activePageRefresh=null;refreshing=false;}
        }
        private async Task PollMonitoringAsync(long generation,CancellationToken token){
            long now=monitoringClock.ElapsedMilliseconds;
            if(now>=nextGeneralRefresh){
                // Full state remains bounded by the normal UI mode; frequent metrics
                // never trigger player scans, connection discovery or page rebuilds.
                nextGeneralRefresh=now+loginPreferences.EffectiveRefreshMilliseconds;
                if(currentPage=="dashboard"||currentPage=="console")await Call("status");
                else await RefreshPageAndStatusAsync();
            }
            token.ThrowIfCancellationRequested();
            if(now>=nextPerformanceRefresh){
                nextPerformanceRefresh=now+loginPreferences.PerformanceRefreshMilliseconds;
                string server=selectedServerId;var result=await Call("monitoring.metrics",null,server);
                token.ThrowIfCancellationRequested();if(generation==pageGeneration&&server==selectedServerId)ReadPerformanceMetrics(result);
            }
            token.ThrowIfCancellationRequested();
            var consoleRefresh=currentPage=="console"?pageRefresh:DetachedConsoleVisible?detachedConsoleRefresh:null;
            if(consoleRefresh!=null&&now>=nextConsoleRefresh){
                nextConsoleRefresh=now+loginPreferences.ConsoleRefreshMilliseconds;await consoleRefresh();
            }
        }
        private void ReadPerformanceMetrics(Dictionary<string,object> result){
            object raw;var sample=result.TryGetValue("server",out raw)?Ui.Map(raw):Ui.Obj();
            if(!Ui.Bool(result,"available"))serverPresentation.Server["metrics_valid"]=false;
            // Lightweight samples do not overwrite readiness, lifecycle or operation.
            foreach(string key in new[]{"pid","cpu_percent","memory_mb","uptime_seconds","metrics_valid","metrics_updated_at"})
                if(sample.TryGetValue(key,out raw))serverPresentation.Server[key]=raw;
            if(dashboardStateChanged!=null)dashboardStateChanged(serverPresentation);
        }
    }
}
